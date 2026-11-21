/** Vite resolves bundled image imports to content-hashed production URLs. */
declare module '*.png' {
  const url: string
  export default url
}
