// Hand-written declaration SUBSET of React 19 / ReactDOM / JSX, used only where @types/react cannot be installed (offline).
// It types exactly the APIs this UI uses (generic hooks, typed event handlers) so `tsc --strict` checks the UI's own code.
// It is NOT @types/react. With network access, run `npm install --prefix ui` (package.json) and delete this file; tsconfig then uses the real types.
interface ChangeEvt { target: { value: string; checked: boolean } }
interface MouseEvt { target: unknown }
type DomProps = {
  [attr: string]: unknown;
  onChange?: (e: ChangeEvt) => void;
  onClick?: (e: MouseEvt) => void;
  className?: string;
  key?: string | number;
};
declare namespace JSX {
  interface Element {}
  interface ElementChildrenAttribute { children: unknown }
  interface IntrinsicAttributes { key?: string | number }
  interface IntrinsicElements { [tag: string]: DomProps }
}
declare module "react" {
  export type ReactNode = unknown;
  export type ReactElement = JSX.Element;
  export interface Context<T> { Provider: (props: { value: T; children?: ReactNode }) => JSX.Element; readonly __t?: T }
  export function useState<T>(init: T | (() => T)): [T, (v: T | ((prev: T) => T)) => void];
  export function useEffect(fn: () => void | (() => void), deps?: readonly unknown[]): void;
  export function useCallback<T extends (...a: never[]) => unknown>(fn: T, deps: readonly unknown[]): T;
  export function useMemo<T>(fn: () => T, deps: readonly unknown[]): T;
  export function useRef<T>(init: T): { current: T };
  export function createContext<T>(v: T): Context<T>;
  export function useContext<T>(c: Context<T>): T;
}
declare module "react/jsx-runtime" {
  export const jsx: unknown; export const jsxs: unknown; export const Fragment: unknown;
}
declare module "react-dom/client" {
  export function createRoot(el: Element): { render(node: JSX.Element): void };
}
