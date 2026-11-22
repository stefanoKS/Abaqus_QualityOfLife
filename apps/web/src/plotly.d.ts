declare module 'plotly.js-basic-dist-min' {
  const Plotly: {
    react: (el: HTMLElement, data: unknown, layout: unknown, config: unknown) => Promise<void>
    restyle: (el: HTMLElement, update: unknown, traces: number[]) => Promise<void>
    purge: (el: HTMLElement) => void
    Plots: { resize: (el: HTMLElement) => void }
  }
  export default Plotly
}
