// Runtime configuration for the territory workspace. Plain script so it can be edited on a
// deployment without a build step. Tiles: OpenStreetMap's public tiles are fine for light
// internal use with attribution; switch tileUrl to a paid provider for heavier use.
window.BG_CONFIG = {
  tileUrl: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  tileAttribution: "&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors",
  minZoom: 4,
  maxZoom: 18,
  dataMinZoom: 9,
  defaultCenter: [39.5, -98.35],
  defaultZoom: 5,
};
