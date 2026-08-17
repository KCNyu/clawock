/**
 * CSS Modules ambient declaration (same shape as the Harness client packages):
 * the build's lightningcss pass turns a `*.module.css` import into the hashed
 * local-name map and injects the stylesheet as a loader-owned `<style>` tag.
 */
declare module '*.module.css' {
  const classes: Record<string, string>
  export default classes
}
