from __future__ import annotations

GALLERY_PROMPTS = (
    {
        "id": "precise-typography-packaging",
        "label": "Precise typography and packaging",
        "prompt": (
            "Create a premium product package on a white studio set, with crisp "
            "micro-typography, clean label hierarchy, embossed paper texture, "
            "precise edges, accurate shadows, and a restrained editorial layout. "
            "The packaging should feel real, manufacturable, and visually exact."
        ),
    },
    {
        "id": "photorealistic-people-materials",
        "label": "Photorealistic people and materials",
        "prompt": (
            "Photorealistic portrait scene of two coworkers in a daylight workshop, "
            "showing natural skin detail, believable hand poses, brushed metal, "
            "matte plastic, wool fabric, glass reflections, and subtle mixed lighting."
        ),
    },
    {
        "id": "imaginative-spatial-composition",
        "label": "Imaginative spatial composition",
        "prompt": (
            "An imaginative architectural composition in a vast zero-gravity atrium, "
            "with layered depth, floating forms, elegant perspective shifts, luminous "
            "materials, and a strong sense of spatial scale without becoming chaotic."
        ),
    },
)

GALLERY_GUIDANCE = (
    "Run scripts/generate_gallery.py to generate 15 comparison images "
    "(3 prompts × 5 models) under static/gallery and create manifest.json."
)
