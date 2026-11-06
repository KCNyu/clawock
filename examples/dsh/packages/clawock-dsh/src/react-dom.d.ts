/**
 * The DSH client loader provides `react-dom` in its module table (verified on
 * 0.2.2-rc.1, 2026-11-06). This package carries no React runtime dependency of
 * its own, so only the one function the client bundle needs is declared here;
 * @types/react-dom would be a devDependency for a single signature.
 */
declare module 'react-dom' {
  import type { ReactElement, ReactNode } from 'react'
  export function createPortal(children: ReactNode, container: Element | DocumentFragment): ReactElement
}
