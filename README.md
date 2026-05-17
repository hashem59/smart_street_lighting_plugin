# smart_street_lighting_plugin

Plumbing library for an AS/NZS 1158-compliant smart street lighting design
system. The library is the supporting code for a Deakin University SIT764
capstone notebook; the notebook is the single deliverable, this package
is what it imports.

## What's in here

| Module | Responsibility |
|---|---|
| `smart_street_lighting.engine` | Deterministic AS/NZS 1158 calculation engine: P-category table, `design_lighting`, `verify_design` (photometric lumen-method check), `size_solar_alternative`, energy / LCC / CO₂ / payback math. **This is the project's IP.** |
| `smart_street_lighting.osm` | Overpass + Nominatim fallback resolver for parks and pathways. Geometric helpers (`haversine`, `measure_polyline_length`, `find_intersections`, `find_entry_points`, `place_lights_on_polyline`, `bounds_from_osm_boundary`). |
| `smart_street_lighting.llm` | LM Studio client (`chat_completion`, `embed`) plus LlamaIndex adapters (`LMStudioLLM`, `LMStudioEmbedding`). Model names and the base URL are passed in by the caller so the marker can see them. |
| `smart_street_lighting.rag` | ChromaDB + LlamaIndex ingestion (`ingest_documents`, `load_existing_index`) and a `create_query_engine` helper that injects a caller-supplied system prompt. |

## Install

```bash
# Engine + OSM only
pip install git+https://github.com/hashem59/smart_street_lighting_plugin.git

# Plus RAG pipeline (LlamaIndex + ChromaDB)
pip install "smart-street-lighting-plugin[rag] @ git+https://github.com/hashem59/smart_street_lighting_plugin.git"

# Everything (RAG + matplotlib / folium for the notebook)
pip install "smart-street-lighting-plugin[all] @ git+https://github.com/hashem59/smart_street_lighting_plugin.git"
```

## Quick start

```python
from smart_street_lighting import design_lighting, verify_design, format_design_report

design = design_lighting(
    location_name="Fitzroy Gardens Main Pathway",
    pathway_length_m=200,
    pathway_width_m=3.0,
    activity_level="high",
    location_type="park_path",
)
print(format_design_report(design))

check = verify_design(design)
print(f"Photometric check: predicted {check['predicted_avg_lux']} lx vs "
      f"required {check['required_avg_lux']} lx -> "
      f"{'PASS' if check['pass'] else 'FAIL'}")
```

## What's intentionally **not** here

- **No global config / env-loading.** Model names, base URLs, and timeouts
  are constructor / function arguments. The notebook sets them once, in a
  visible cell, so the marker can see exactly which models were used.
- **No on-disk caching.** The notebook is a single-shot deliverable; a
  silent cache hiding network behaviour was deliberately removed when the
  code was lifted into this library.
- **No data-science narrative or algorithms.** The notebook holds those
  inline. The library is plumbing only.

## License

MIT. See `LICENSE`.
