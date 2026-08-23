/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Optional raster tile URL template.
   *
   * Unset by default, and it should stay unset for a live demo: the map draws
   * locally generated geometry so it cannot fail on venue wifi. Point this at
   * a tile host only where connectivity is known to be good.
   */
  readonly VITE_PHAROS_TILES?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
