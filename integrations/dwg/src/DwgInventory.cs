using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using ACadSharp;
using ACadSharp.Entities;
using ACadSharp.Exceptions;
using ACadSharp.IO;
using ACadSharp.Tables;
using CSMath;

// Application-owned DWG reader helper. Reads a DWG directly through ACadSharp
// (MIT) and emits the model-space inventory as JSON on stdout. No ODA, no DXF
// intermediate, no network. Geometry only: engineering roles are decided in the
// Python importer so the canonical model stays the single source of truth.
internal static class DwgInventory
{
    private const int MaxInsertDepth = 4;
    private const int MaxEntities = 200000;

    private static readonly List<string> Warnings = new List<string>();
    private static readonly SortedDictionary<string, int> Unknown = new SortedDictionary<string, int>(StringComparer.Ordinal);
    private static readonly List<string> UnknownHandles = new List<string>();

    private static int Main(string[] args)
    {
        if (args.Length != 1)
        {
            EmitError("usage", "Usage: dwg-inventory.exe <drawing.dwg>");
            return 64;
        }
        string path = args[0];
        try
        {
            byte[] bytes = File.ReadAllBytes(path);
            if (bytes.Length < 32)
            {
                EmitError("corrupt", "The file is too small to be a DWG drawing.");
                return 65;
            }
            string version = Encoding.ASCII.GetString(bytes, 0, 6);
            if (!version.StartsWith("AC", StringComparison.Ordinal))
            {
                EmitError("corrupt", "The file does not start with a DWG version tag.");
                return 65;
            }
            CadDocument document = DwgReader.Read(path, OnNotification);
            if (document == null)
            {
                EmitError("decode", "The reader returned no document.");
                return 66;
            }
            Console.Out.Write(Inventory(document, path, bytes, version));
            return 0;
        }
        catch (CadNotSupportedException error)
        {
            EmitError("unsupported-version", error.Message);
            return 67;
        }
        catch (DwgException error)
        {
            EmitError("decode", error.Message);
            return 66;
        }
        catch (Exception error)
        {
            EmitError("decode", error.GetType().Name + ": " + error.Message);
            return 66;
        }
    }

    private static void OnNotification(object sender, NotificationEventArgs e)
    {
        string message = e.Message == null ? "(no message)" : e.Message;
        Warnings.Add(e.NotificationType + ": " + message);
    }

    private static string Inventory(CadDocument document, string path, byte[] bytes, string version)
    {
        Json json = new Json();
        json.BeginObject();
        json.Name("reader").BeginObject();
        json.Name("name").Value("ACadSharp");
        json.Name("version").Value("3.8.35");
        json.Name("license").Value("MIT");
        json.Name("entryPoint").Value("DwgReader.Read");
        json.EndObject();

        json.Name("source").BeginObject();
        json.Name("path").Value(Path.GetFileName(path));
        json.Name("bytes").Value(bytes.Length);
        json.Name("sha256").Value(Sha256(bytes));
        json.Name("version").Value(version);
        json.Name("insUnits").Value((int)document.Header.InsUnits);
        json.Name("insUnitsName").Value(document.Header.InsUnits.ToString());
        json.EndObject();

        List<EntityReport> report = new List<EntityReport>();
        foreach (Entity entity in document.ModelSpace.Entities)
        {
            if (report.Count >= MaxEntities)
            {
                Warnings.Add("limit: stopped after " + MaxEntities + " model-space entities.");
                break;
            }
            Collect(entity, entity.Layer == null ? "" : entity.Layer.Name, report, 0, "");
        }

        SortedDictionary<string, int> counts = new SortedDictionary<string, int>(StringComparer.Ordinal);
        foreach (EntityReport item in report)
        {
            if (!counts.ContainsKey(item.Type))
            {
                counts[item.Type] = 0;
            }
            counts[item.Type] = counts[item.Type] + 1;
        }

        json.Name("counts").BeginObject();
        foreach (KeyValuePair<string, int> pair in counts)
        {
            json.Name(pair.Key).Value(pair.Value);
        }
        json.EndObject();

        json.Name("unknown").BeginObject();
        foreach (KeyValuePair<string, int> pair in Unknown)
        {
            json.Name(pair.Key).Value(pair.Value);
        }
        json.EndObject();

        json.Name("unknownHandles");
        json.BeginArray();
        foreach (string handle in UnknownHandles)
        {
            json.Value(handle);
        }
        json.EndArray();

        json.Name("layers");
        json.BeginArray();
        foreach (Layer layer in document.Layers)
        {
            json.BeginObject();
            json.Name("name").Value(layer.Name);
            json.Name("on").Value(layer.IsOn);
            json.Name("entities").Value(report.Count(x => string.Equals(x.Layer, layer.Name, StringComparison.OrdinalIgnoreCase)));
            json.EndObject();
        }
        json.EndArray();

        json.Name("blocks");
        json.BeginArray();
        foreach (BlockRecord block in document.BlockRecords)
        {
            if (block.IsAnonymous)
            {
                continue;
            }
            json.BeginObject();
            json.Name("name").Value(block.Name);
            json.Name("entities").Value(block.Entities.Count());
            json.Name("placed").Value(report.Count(x => string.Equals(x.ViaBlock, block.Name, StringComparison.Ordinal)));
            json.EndObject();
        }
        json.EndArray();

        json.Name("entities");
        json.BeginArray();
        foreach (EntityReport item in report)
        {
            item.WriteTo(json);
        }
        json.EndArray();

        json.Name("warnings");
        json.BeginArray();
        foreach (string warning in Warnings)
        {
            json.Value(warning);
        }
        json.EndArray();

        json.EndObject();
        return json.ToString();
    }

    private static void Collect(Entity entity, string layer, List<EntityReport> report, int depth, string viaBlock)
    {
        string type = entity.GetType().Name.ToUpperInvariant();
        EntityReport item = new EntityReport();
        item.Handle = Handle(entity);
        item.Type = type;
        item.Layer = layer;
        item.ViaBlock = viaBlock;
        item.Invisible = entity.IsInvisible;
        Line line = entity as Line;
        Arc arc = entity as Arc;
        Circle circle = entity as Circle;
        Ellipse ellipse = entity as Ellipse;
        LwPolyline polyline = entity as LwPolyline;
        Spline spline = entity as Spline;
        Point point = entity as Point;
        Insert insert = entity as Insert;
        if (line != null)
        {
            // LINE endpoints are already world coordinates (WCS); no OCS applies.
            item.Start = line.StartPoint;
            item.End = line.EndPoint;
        }
        else if (arc != null)
        {
            item.Normal = arc.Normal;
            if (!IsPlanar(arc.Normal))
            {
                // The product is 2D. Report the typed reason instead of projecting
                // a tilted circle onto XY, which would invent a different curve.
                item.TransformError = "unsupported-nonplanar";
                item.Radius = arc.Radius;
                Warnings.Add("arc " + item.Handle + ": extrusion (" + arc.Normal + ") is not parallel to the world Z axis; the planar 2D model cannot represent it.");
            }
            else
            {
                Matrix4 basis = Matrix4.GetArbitraryAxis(arc.Normal);
                double ocsSweep = NormalizeSweep(arc.EndAngle - arc.StartAngle);
                XYZ center = basis * arc.Center;
                XYZ ocsStart = new XYZ(
                    arc.Center.X + arc.Radius * Math.Cos(arc.StartAngle),
                    arc.Center.Y + arc.Radius * Math.Sin(arc.StartAngle),
                    arc.Center.Z);
                XYZ ocsEnd = new XYZ(
                    arc.Center.X + arc.Radius * Math.Cos(arc.EndAngle),
                    arc.Center.Y + arc.Radius * Math.Sin(arc.EndAngle),
                    arc.Center.Z);
                XYZ ocsMid = new XYZ(
                    arc.Center.X + arc.Radius * Math.Cos(arc.StartAngle + ocsSweep / 2.0),
                    arc.Center.Y + arc.Radius * Math.Sin(arc.StartAngle + ocsSweep / 2.0),
                    arc.Center.Z);
                item.Center = center;
                item.Radius = arc.Radius;
                item.Start = basis * ocsStart;
                item.End = basis * ocsEnd;
                item.Mid = basis * ocsMid;
                item.OcsCenter = arc.Center;
                item.OcsStartAngle = arc.StartAngle;
                item.OcsEndAngle = arc.EndAngle;
                // OCS arcs are counter-clockwise by definition. A -Z extrusion
                // reflects the plane, so the equivalent WCS traversal is clockwise.
                item.Sweep = (arc.Normal.Z < 0 ? -1.0 : 1.0) * ocsSweep;
                item.StartAngle = Math.Atan2(item.Start.Value.Y - center.Y, item.Start.Value.X - center.X);
                item.EndAngle = Math.Atan2(item.End.Value.Y - center.Y, item.End.Value.X - center.X);
            }
        }
        else if (circle != null)
        {
            item.Normal = circle.Normal;
            if (!IsPlanar(circle.Normal))
            {
                item.TransformError = "unsupported-nonplanar";
                item.Radius = circle.Radius;
                Warnings.Add("circle " + item.Handle + ": extrusion (" + circle.Normal + ") is not parallel to the world Z axis; the planar 2D model cannot represent it.");
            }
            else
            {
                item.Center = Matrix4.GetArbitraryAxis(circle.Normal) * circle.Center;
                item.Radius = circle.Radius;
            }
        }
        else if (ellipse != null)
        {
            item.Center = ellipse.Center;
            item.MajorAxis = ellipse.MajorAxisEndPoint;
            item.Radius = ellipse.RadiusRatio;
            item.StartAngle = ellipse.StartParameter;
            item.EndAngle = ellipse.EndParameter;
        }
        else if (polyline != null)
        {
            item.Normal = polyline.Normal;
            if (!IsPlanar(polyline.Normal))
            {
                item.TransformError = "unsupported-nonplanar";
                Warnings.Add("polyline " + item.Handle + ": extrusion (" + polyline.Normal + ") is not parallel to the world Z axis; the planar 2D model cannot represent it.");
            }
            else
            {
                Matrix4 basis = Matrix4.GetArbitraryAxis(polyline.Normal);
                double bulgeSign = polyline.Normal.Z < 0 ? -1.0 : 1.0;
                item.Vertices = polyline.Vertices.Select(v => new VertexReport
                {
                    Point = basis * new XYZ(v.Location.X, v.Location.Y, polyline.Elevation),
                    Bulge = bulgeSign * v.Bulge
                }).ToList();
                item.Elevation = polyline.Elevation;
                item.Closed = polyline.IsClosed;
            }
        }
        else if (spline != null)
        {
            item.Degree = spline.Degree;
            item.ControlPoints = spline.ControlPoints.ToList();
            item.FitPoints = spline.FitPoints.ToList();
            item.Knots = spline.Knots.ToList();
            item.Weights = spline.Weights.ToList();
            item.Closed = spline.IsClosed;
            item.Periodic = spline.IsPeriodic;
            item.StartTangent = spline.StartTangent;
            item.EndTangent = spline.EndTangent;
            item.Flags = (int)spline.Flags;
            if (!spline.HasValidKnotCount)
            {
                Warnings.Add("spline " + item.Handle + ": knot count does not match control points.");
            }
        }
        else if (point != null)
        {
            item.Start = point.Location;
        }
        else if (insert != null)
        {
            item.Start = insert.InsertPoint;
            item.Rotation = insert.Rotation;
            item.ScaleX = insert.XScale;
            item.ScaleY = insert.YScale;
            item.ScaleZ = insert.ZScale;
            item.BlockName = insert.Block == null ? "" : insert.Block.Name;
            item.Columns = (int)insert.ColumnCount;
            item.Rows = (int)insert.RowCount;
            report.Add(item);
            if (depth >= MaxInsertDepth)
            {
                Warnings.Add("insert " + item.Handle + ": nesting deeper than " + MaxInsertDepth + " levels, block geometry not expanded.");
                return;
            }
            if (insert.Block == null || insert.Block.Entities == null || !insert.Block.Entities.Any())
            {
                Warnings.Add("insert " + item.Handle + ": block " + item.BlockName + " has no entities to expand.");
                return;
            }
            int index = 0;
            foreach (Entity child in insert.Block.Entities)
            {
                index = index + 1;
                List<EntityReport> expanded = new List<EntityReport>();
                Collect(child, item.Layer, expanded, depth + 1, item.BlockName);
                foreach (EntityReport placed in expanded)
                {
                    placed.Instance = item.Handle + "/" + index;
                    if (!placed.TryTransform(insert, Warnings))
                    {
                        continue;
                    }
                    report.Add(placed);
                }
            }
            return;
        }
        else
        {
            if (!Unknown.ContainsKey(type))
            {
                Unknown[type] = 0;
            }
            Unknown[type] = Unknown[type] + 1;
            if (UnknownHandles.Count < 200)
            {
                UnknownHandles.Add(item.Handle + " " + type + " on layer " + layer);
            }
            return;
        }
        report.Add(item);
    }

    private static string Handle(CadObject cadObject)
    {
        return cadObject.Handle.ToString("X", CultureInfo.InvariantCulture);
    }

    // Within the 1e-9 rounding used by the inventory serializer, only a normal
    // parallel to the world Z axis keeps a planar circular curve circular in XY.
    private static bool IsPlanar(XYZ normal)
    {
        double length = Math.Sqrt(normal.X * normal.X + normal.Y * normal.Y + normal.Z * normal.Z);
        if (length < 1e-12)
        {
            return false;
        }
        return Math.Abs(normal.X / length) < 1e-9
            && Math.Abs(normal.Y / length) < 1e-9
            && Math.Abs(normal.Z / length) > 1.0 - 1e-9;
    }

    private static double NormalizeSweep(double sweep)
    {
        const double tau = Math.PI * 2.0;
        double value = sweep % tau;
        if (value < 0)
        {
            value += tau;
        }
        return value;
    }

    private static string Sha256(byte[] bytes)
    {
        using (System.Security.Cryptography.SHA256 algorithm = System.Security.Cryptography.SHA256.Create())
        {
            byte[] hash = algorithm.ComputeHash(bytes);
            StringBuilder builder = new StringBuilder(hash.Length * 2);
            foreach (byte value in hash)
            {
                builder.Append(value.ToString("x2", CultureInfo.InvariantCulture));
            }
            return builder.ToString();
        }
    }

    private static void EmitError(string code, string message)
    {
        Json json = new Json();
        json.BeginObject();
        json.Name("error").BeginObject();
        json.Name("code").Value(code);
        json.Name("message").Value(message == null ? "" : message);
        json.EndObject();
        json.EndObject();
        Console.Out.Write(json.ToString());
    }

    private sealed class VertexReport
    {
        public XYZ Point;
        public double Bulge;

        public void WriteTo(Json json)
        {
            json.BeginObject();
            json.Name("x").Value(Point.X);
            json.Name("y").Value(Point.Y);
            json.Name("bulge").Value(Bulge);
            json.EndObject();
        }
    }

    private sealed class EntityReport
    {
        public string Handle;
        public string Type;
        public string Layer;
        public string ViaBlock;
        public string Instance;
        public bool Invisible;
        public XYZ? Start;
        public XYZ? End;
        public XYZ? Center;
        public XYZ? Normal;
        public XYZ? Mid;
        public XYZ? OcsCenter;
        public double? OcsStartAngle;
        public double? OcsEndAngle;
        public double? Sweep;
        public double? Elevation;
        public string TransformError;
        public double? Radius;
        public double? StartAngle;
        public double? EndAngle;
        public XYZ? MajorAxis;
        public List<VertexReport> Vertices;
        public bool? Closed;
        public bool? Periodic;
        public int? Degree;
        public List<XYZ> ControlPoints;
        public List<XYZ> FitPoints;
        public List<double> Knots;
        public List<double> Weights;
        public XYZ? StartTangent;
        public XYZ? EndTangent;
        public int? Flags;
        public double? Rotation;
        public double? ScaleX;
        public double? ScaleY;
        public double? ScaleZ;
        public string BlockName;
        public int? Columns;
        public int? Rows;

        // Applies the INSERT transform in place. False means the entity cannot be
        // placed exactly and must be reported rather than guessed.
        public bool TryTransform(Insert insert, List<string> warnings)
        {
            double sx = insert.XScale;
            double sy = insert.YScale;
            double sz = insert.ZScale;
            if (Math.Abs(sx) < 1e-12 || Math.Abs(sy) < 1e-12)
            {
                warnings.Add("insert " + insert.Handle.ToString("X", CultureInfo.InvariantCulture) + ": zero scale cannot be expanded.");
                return false;
            }
            double radians = insert.Rotation;
            bool mirrored = sx * sy < 0;
            if (mirrored)
            {
                warnings.Add("insert " + insert.Handle.ToString("X", CultureInfo.InvariantCulture) + ": mirrored block instance expanded with its signed scale; arc sweep direction is reversed.");
            }
            XYZ origin = insert.InsertPoint;
            Start = Apply(Start, origin, radians, sx, sy, sz);
            End = Apply(End, origin, radians, sx, sy, sz);
            Center = Apply(Center, origin, radians, sx, sy, sz);
            Mid = Apply(Mid, origin, radians, sx, sy, sz);
            StartTangent = ApplyDirection(StartTangent, radians, sx, sy);
            EndTangent = ApplyDirection(EndTangent, radians, sx, sy);
            MajorAxis = ApplyDirection(MajorAxis, radians, sx, sy);
            if (ControlPoints != null)
            {
                ControlPoints = ControlPoints.Select(p => ApplyPoint(p, origin, radians, sx, sy, sz)).ToList();
            }
            if (FitPoints != null)
            {
                FitPoints = FitPoints.Select(p => ApplyPoint(p, origin, radians, sx, sy, sz)).ToList();
            }
            if (Vertices != null && Vertices.Count > 0)
            {
                if (Math.Abs(Math.Abs(sx) - Math.Abs(sy)) > 1e-12)
                {
                    warnings.Add("insert " + insert.Handle.ToString("X", CultureInfo.InvariantCulture) + ": non-uniform scale on a bulged polyline, arcs are approximate.");
                }
                Vertices = Vertices.Select(v => new VertexReport
                {
                    Point = ApplyPoint(v.Point, origin, radians, sx, sy, sz),
                    Bulge = mirrored ? -v.Bulge : v.Bulge
                }).ToList();
            }
            if (Radius.HasValue)
            {
                if (Math.Abs(Math.Abs(sx) - Math.Abs(sy)) > 1e-12)
                {
                    warnings.Add("insert " + insert.Handle.ToString("X", CultureInfo.InvariantCulture) + ": non-uniform scale turns circular arcs into ellipses; radius uses the geometric mean.");
                }
                Radius = Radius.Value * Math.Sqrt(Math.Abs(sx * sy));
            }
            if (Sweep.HasValue)
            {
                Sweep = mirrored ? -Sweep.Value : Sweep.Value;
            }
            if (StartAngle.HasValue && Start.HasValue && Center.HasValue)
            {
                StartAngle = Math.Atan2(Start.Value.Y - Center.Value.Y, Start.Value.X - Center.Value.X);
            }
            if (EndAngle.HasValue && End.HasValue && Center.HasValue)
            {
                EndAngle = Math.Atan2(End.Value.Y - Center.Value.Y, End.Value.X - Center.Value.X);
            }
            if (Rotation.HasValue)
            {
                Rotation = Rotation.Value + radians;
            }
            return true;
        }

        private static XYZ? Apply(XYZ? point, XYZ origin, double radians, double sx, double sy, double sz)
        {
            if (!point.HasValue)
            {
                return null;
            }
            return ApplyPoint(point.Value, origin, radians, sx, sy, sz);
        }

        private static XYZ ApplyPoint(XYZ point, XYZ origin, double radians, double sx, double sy, double sz)
        {
            double x = point.X * sx;
            double y = point.Y * sy;
            double z = point.Z * sz;
            double cos = Math.Cos(radians);
            double sin = Math.Sin(radians);
            return new XYZ(x * cos - y * sin + origin.X, x * sin + y * cos + origin.Y, z + origin.Z);
        }

        private static XYZ? ApplyDirection(XYZ? vector, double radians, double sx, double sy)
        {
            if (!vector.HasValue)
            {
                return null;
            }
            double x = vector.Value.X * sx;
            double y = vector.Value.Y * sy;
            double cos = Math.Cos(radians);
            double sin = Math.Sin(radians);
            return new XYZ(x * cos - y * sin, x * sin + y * cos, vector.Value.Z);
        }

        public void WriteTo(Json json)
        {
            json.BeginObject();
            json.Name("handle").Value(Handle);
            json.Name("type").Value(Type);
            json.Name("layer").Value(Layer == null ? "" : Layer);
            if (!string.IsNullOrEmpty(ViaBlock))
            {
                json.Name("viaBlock").Value(ViaBlock);
                json.Name("instance").Value(Instance == null ? "" : Instance);
            }
            if (Invisible)
            {
                json.Name("invisible").Value(true);
            }
            if (Start.HasValue)
            {
                json.Name("start").Point(Start.Value);
            }
            if (End.HasValue)
            {
                json.Name("end").Point(End.Value);
            }
            if (Center.HasValue)
            {
                json.Name("center").Point(Center.Value);
            }
            if (Normal.HasValue)
            {
                json.Name("normal").Point(Normal.Value);
            }
            if (OcsCenter.HasValue)
            {
                json.Name("ocs").BeginObject();
                json.Name("center").Point(OcsCenter.Value);
                json.Name("startAngle").RawValue(OcsStartAngle.Value);
                json.Name("endAngle").RawValue(OcsEndAngle.Value);
                json.EndObject();
            }
            if (Mid.HasValue)
            {
                json.Name("mid").Point(Mid.Value);
            }
            if (Sweep.HasValue)
            {
                // The sweep decides quarter-turn segmentation. Keep full double
                // precision so an exact 90-degree arc is not rounded just above
                // one segment and split in two.
                json.Name("sweep").RawValue(Sweep.Value);
            }
            if (Elevation.HasValue)
            {
                json.Name("elevation").Value(Elevation.Value);
            }
            if (!string.IsNullOrEmpty(TransformError))
            {
                json.Name("transformError").Value(TransformError);
            }
            if (Radius.HasValue)
            {
                json.Name("radius").Value(Radius.Value);
            }
            if (StartAngle.HasValue)
            {
                json.Name("startAngle").Value(StartAngle.Value);
            }
            if (EndAngle.HasValue)
            {
                json.Name("endAngle").Value(EndAngle.Value);
            }
            if (MajorAxis.HasValue)
            {
                json.Name("majorAxis").Point(MajorAxis.Value);
            }
            if (Degree.HasValue)
            {
                json.Name("degree").Value(Degree.Value);
            }
            if (ControlPoints != null)
            {
                json.Name("controlPoints").Points(ControlPoints);
            }
            if (FitPoints != null)
            {
                json.Name("fitPoints").Points(FitPoints);
            }
            if (Knots != null && Knots.Count > 0)
            {
                json.Name("knots").Numbers(Knots);
            }
            if (Weights != null && Weights.Count > 0)
            {
                json.Name("weights").Numbers(Weights);
            }
            if (StartTangent.HasValue && !IsZero(StartTangent.Value))
            {
                json.Name("startTangent").Point(StartTangent.Value);
            }
            if (EndTangent.HasValue && !IsZero(EndTangent.Value))
            {
                json.Name("endTangent").Point(EndTangent.Value);
            }
            if (Flags.HasValue)
            {
                json.Name("flags").Value(Flags.Value);
            }
            if (Closed.HasValue)
            {
                json.Name("closed").Value(Closed.Value);
            }
            if (Periodic.HasValue)
            {
                json.Name("periodic").Value(Periodic.Value);
            }
            if (Vertices != null)
            {
                json.Name("vertices");
                json.BeginArray();
                foreach (VertexReport vertex in Vertices)
                {
                    vertex.WriteTo(json);
                }
                json.EndArray();
            }
            if (BlockName != null)
            {
                json.Name("block").Value(BlockName);
            }
            if (Rotation.HasValue)
            {
                json.Name("rotation").Value(Rotation.Value);
            }
            if (ScaleX.HasValue)
            {
                json.Name("scaleX").Value(ScaleX.Value);
            }
            if (ScaleY.HasValue)
            {
                json.Name("scaleY").Value(ScaleY.Value);
            }
            if (ScaleZ.HasValue)
            {
                json.Name("scaleZ").Value(ScaleZ.Value);
            }
            if (Columns.HasValue)
            {
                json.Name("columns").Value(Columns.Value);
            }
            if (Rows.HasValue)
            {
                json.Name("rows").Value(Rows.Value);
            }
            json.EndObject();
        }

        private static bool IsZero(XYZ value)
        {
            return Math.Abs(value.X) < 1e-12 && Math.Abs(value.Y) < 1e-12 && Math.Abs(value.Z) < 1e-12;
        }
    }

    private sealed class Json
    {
        private readonly StringBuilder builder = new StringBuilder(65536);
        private bool first = true;

        public Json BeginObject()
        {
            Separate();
            builder.Append('{');
            first = true;
            return this;
        }

        public Json EndObject()
        {
            builder.Append('}');
            first = false;
            return this;
        }

        public Json BeginArray()
        {
            Separate();
            builder.Append('[');
            first = true;
            return this;
        }

        public Json EndArray()
        {
            builder.Append(']');
            first = false;
            return this;
        }

        public Json Name(string name)
        {
            Separate();
            WriteString(name);
            builder.Append(':');
            first = true;
            return this;
        }

        public Json Value(string text)
        {
            Separate();
            WriteString(text);
            first = false;
            return this;
        }

        public Json Value(int number)
        {
            Separate();
            builder.Append(number.ToString(CultureInfo.InvariantCulture));
            first = false;
            return this;
        }

        public Json Value(bool flag)
        {
            Separate();
            builder.Append(flag ? "true" : "false");
            first = false;
            return this;
        }

        public Json Value(double number)
        {
            Separate();
            builder.Append(Round(number).ToString("R", CultureInfo.InvariantCulture));
            first = false;
            return this;
        }

        public Json RawValue(double number)
        {
            Separate();
            builder.Append(number.ToString("R", CultureInfo.InvariantCulture));
            first = false;
            return this;
        }

        public Json Point(XYZ point)
        {
            Separate();
            builder.Append('[');
            builder.Append(Round(point.X).ToString("R", CultureInfo.InvariantCulture));
            builder.Append(',');
            builder.Append(Round(point.Y).ToString("R", CultureInfo.InvariantCulture));
            builder.Append(',');
            builder.Append(Round(point.Z).ToString("R", CultureInfo.InvariantCulture));
            builder.Append(']');
            first = false;
            return this;
        }

        public Json Points(List<XYZ> points)
        {
            Separate();
            builder.Append('[');
            for (int i = 0; i < points.Count; i++)
            {
                if (i > 0)
                {
                    builder.Append(',');
                }
                builder.Append('[');
                builder.Append(Round(points[i].X).ToString("R", CultureInfo.InvariantCulture));
                builder.Append(',');
                builder.Append(Round(points[i].Y).ToString("R", CultureInfo.InvariantCulture));
                builder.Append(',');
                builder.Append(Round(points[i].Z).ToString("R", CultureInfo.InvariantCulture));
                builder.Append(']');
            }
            builder.Append(']');
            first = false;
            return this;
        }

        public Json Numbers(List<double> numbers)
        {
            Separate();
            builder.Append('[');
            for (int i = 0; i < numbers.Count; i++)
            {
                if (i > 0)
                {
                    builder.Append(',');
                }
                builder.Append(Round(numbers[i]).ToString("R", CultureInfo.InvariantCulture));
            }
            builder.Append(']');
            first = false;
            return this;
        }

        public override string ToString()
        {
            return builder.ToString();
        }

        private static double Round(double value)
        {
            if (double.IsNaN(value) || double.IsInfinity(value))
            {
                return 0.0;
            }
            return Math.Round(value, 9);
        }

        private void Separate()
        {
            if (!first)
            {
                builder.Append(',');
            }
            first = false;
        }

        private void WriteString(string text)
        {
            builder.Append('"');
            foreach (char character in text)
            {
                switch (character)
                {
                    case '"':
                        builder.Append("\\\"");
                        break;
                    case '\\':
                        builder.Append("\\\\");
                        break;
                    case '\n':
                        builder.Append("\\n");
                        break;
                    case '\r':
                        builder.Append("\\r");
                        break;
                    case '\t':
                        builder.Append("\\t");
                        break;
                    default:
                        if (character < ' ')
                        {
                            builder.Append("\\u");
                            builder.Append(((int)character).ToString("x4", CultureInfo.InvariantCulture));
                        }
                        else
                        {
                            builder.Append(character);
                        }
                        break;
                }
            }
            builder.Append('"');
        }
    }
}
