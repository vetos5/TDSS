# Legacy — Streamlit UI (v3)

This folder contains the original **Streamlit** prototype of the TDSS application (version 3).

It has been superseded by the **Vue 3 + FastAPI** stack (version 4) located in `frontend/` and `backend/`.

## Contents

| File | Description |
|------|-------------|
| `streamlit_ui/main.py` | Full Streamlit UI — weight sliders, Plotly charts, SVG blueprints |
| `streamlit_ui/charts.py` | Stateless Plotly figure factories used by the Streamlit UI |

## Running (if needed)

```bash
pip install streamlit plotly
streamlit run legacy/streamlit_ui/main.py
```
