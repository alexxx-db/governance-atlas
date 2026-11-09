interface Window {
  __AXIOM_BOOTSTRAP__?: {
    apiBase?: string;
    apiContract?: Record<string, string>;
    [key: string]: unknown;
  };
}

interface ImportMetaEnv {
  readonly VITE_AXIOM_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module "*.svg" {
  const src: string;
  export default src;
}

declare module "*.png" {
  const src: string;
  export default src;
}
