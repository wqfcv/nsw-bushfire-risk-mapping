"""
mapping.py
----------
Folium-based interactive visualisation helpers for GEE layers.
Works inside Jupyter / Colab where geemap or folium + a GEE tile
callback are available.
"""

import folium
import ee


def add_ee_layer(self, ee_image, vis_params, name, show=True, opacity=1.0):
    """Monkey-patch method that lets folium.Map draw GEE layers."""
    map_id_dict = ee.Image(ee_image).getMapId(vis_params)
    folium.raster_layers.TileLayer(
        tiles=map_id_dict["tile_fetcher"].url_format,
        attr="Google Earth Engine",
        name=name,
        overlay=True,
        control=True,
        show=show,
        opacity=opacity,
    ).add_to(self)


folium.Map.add_ee_layer = add_ee_layer


RISK_PALETTE = ["#2ecc71", "#f1c40f", "#e67e22", "#c0392b"]
# Low (green) -> Moderate (yellow) -> High (orange) -> Extreme (red)

RISK_VIS = {
    "min": 1,
    "max": 4,
    "palette": RISK_PALETTE,
}

NDVI_VIS = {"min": 0, "max": 1, "palette": ["brown", "yellow", "green"]}
NDMI_VIS = {"min": -0.5, "max": 0.5, "palette": ["red", "white", "blue"]}


def build_risk_map(center_lat, center_lon, risk_image, ndvi_band=None,
                    ndmi_band=None, zoom_start=10):
    """Build a folium map with the risk index layer and optional
    NDVI / NDMI reference layers for comparison.
    """
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom_start,
                    tiles="OpenStreetMap")

    m.add_ee_layer(
        risk_image.select("risk_class"), RISK_VIS, "Bushfire Risk Class"
    )

    if ndvi_band is not None:
        m.add_ee_layer(ndvi_band, NDVI_VIS, "NDVI (fuel load)", show=False)
    if ndmi_band is not None:
        m.add_ee_layer(ndmi_band, NDMI_VIS, "NDMI (moisture)", show=False)

    legend_html = """
    <div style="position: fixed; bottom: 30px; left: 30px; z-index: 9999;
                background: white; padding: 10px 14px; border-radius: 6px;
                box-shadow: 0 1px 4px rgba(0,0,0,0.3); font-size: 13px;">
      <b>Bushfire Risk</b><br>
      <span style="color:#2ecc71;">&#9632;</span> Low<br>
      <span style="color:#f1c40f;">&#9632;</span> Moderate<br>
      <span style="color:#e67e22;">&#9632;</span> High<br>
      <span style="color:#c0392b;">&#9632;</span> Extreme
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))
    folium.LayerControl(collapsed=False).add_to(m)
    return m
