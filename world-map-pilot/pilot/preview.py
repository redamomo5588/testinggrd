"""Quick-look PNG of all layers."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import ListedColormap, BoundaryNorm  # noqa: E402

WC = {10: "#006400", 20: "#ffbb22", 30: "#ffff4c", 40: "#f096ff", 50: "#fa0000", 60: "#b4b4b4",
      70: "#f0f0f0", 80: "#0064c8", 90: "#0096a0", 95: "#00cf75", 100: "#fae6a0"}


def hillshade(dem, res, az=315, alt=45):
    dy, dx = np.gradient(np.nan_to_num(dem, nan=np.nanmean(dem)), res)
    slope = np.pi / 2 - np.arctan(np.hypot(dx, dy))
    aspect = np.arctan2(-dx, dy)
    a, z = np.radians(360 - az + 90), np.radians(alt)
    return np.sin(z) * np.sin(slope) + np.cos(z) * np.cos(slope) * np.cos(a - aspect)


def render(path, grid, L, V):
    ext = (grid.bounds[0], grid.bounds[2], grid.bounds[1], grid.bounds[3])
    fig, ax = plt.subplots(2, 3, figsize=(18, 11), constrained_layout=True)
    a = ax[0, 0]; a.imshow(hillshade(L["dem"], grid.transform.a), cmap="gray", extent=ext)
    im = a.imshow(L["dem"], cmap="terrain", alpha=0.55, extent=ext); fig.colorbar(im, ax=a, shrink=.7)
    a.set_title("Terrain (Copernicus DSM 30m) m")
    a = ax[0, 1]; im = a.imshow(L["canopy"], cmap="Greens", vmin=0, vmax=30, extent=ext)
    fig.colorbar(im, ax=a, shrink=.7); a.set_title("Canopy top height (Meta 1m → 10m block max) m")
    keys = sorted(WC); cm = ListedColormap([WC[k] for k in keys])
    norm = BoundaryNorm(keys + [101], cm.N)
    a = ax[0, 2]; a.imshow(np.ma.masked_equal(L["landcover_fused"], 0), cmap=cm, norm=norm, extent=ext, interpolation="nearest")
    a.set_title("Fused land cover (WorldCover + water + buildings)")
    a = ax[1, 0]
    rgb = np.ones(grid.shape + (3,))
    rgb[L["forest"] == 1] = (0.1, 0.5, 0.1); rgb[L["water"] == 1] = (0.1, 0.4, 0.9)
    a.imshow(rgb, extent=ext); a.set_title("Forest (WC tree ∧ canopy≥5m) / water (fused)")
    a = ax[1, 1]
    V["roads"].plot(ax=a, color="#555", linewidth=0.25)
    V["buildings"].plot(ax=a, color="#c0392b", linewidth=0)
    V["crossroads"][V["crossroads"]["kind"] == "vehicle"].plot(ax=a, color="#f39c12", markersize=0.15)
    a.set_title("Buildings, roads, vehicle crossroads"); a.set_xlim(ext[:2]); a.set_ylim(ext[2:])
    a = ax[1, 2]; a.imshow(hillshade(L["dem"], grid.transform.a), cmap="gray", extent=ext, alpha=.5)
    wm = np.ma.masked_equal(L["water"], 0); a.imshow(wm, cmap=ListedColormap(["#0064c8"]), extent=ext)
    if len(V["water_points"]):
        V["water_points"].plot(ax=a, column="source", markersize=12, legend=True, categorical=True)
    a.set_title("Water bodies + water points")
    for a in ax.flat:
        a.set_xticks([]); a.set_yticks([])
    fig.savefig(path, dpi=110)
    plt.close(fig)
