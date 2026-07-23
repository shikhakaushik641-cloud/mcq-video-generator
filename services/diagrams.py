"""Diagram generation for MCQ videos.

Circuit diagrams are built from a typed "ladder" spec (nodes along a top
rail, connected by horizontal elements; each node may carry one or more
parallel vertical branches down to a shared ground/return rail) — this
covers the series/parallel/nodal-analysis circuits these MCQs use, not
arbitrary schematics.

Rendering is staged: schemdraw is called multiple times with progressively
more of the spec included (wires only -> components -> labelled values),
producing a short sequence of static images that the video composition
crossfades between, instead of a hand-built animated SVG renderer.
"""

from pathlib import Path

import schemdraw
import schemdraw.elements as elm

_ELEMENT_TYPES = {
    "resistor": elm.Resistor,
    "capacitor": elm.Capacitor,
    "inductor": elm.Inductor2,
    "sourcev": elm.SourceV,
    "sourcei": elm.SourceI,
    "wire": elm.Line,
}

NODE_SPACING = 4.2     # horizontal distance between top-rail nodes
BRANCH_SPACING = 1.8   # horizontal gap between parallel branches at one node
BRANCH_HEIGHT = 2.0    # vertical length of a single branch element
GROUND_MARGIN = 0.6    # gap below the lowest branch before the ground bus


def _branch_x_positions(node_x: float, n: int) -> list[float]:
    if n == 1:
        return [node_x]
    span = BRANCH_SPACING * (n - 1)
    start = node_x - span / 2
    return [start + i * BRANCH_SPACING for i in range(n)]


def _draw_circuit(spec: dict, stage: str) -> schemdraw.Drawing:
    """stage: 'wires' | 'components' | 'labelled'

    Every element is placed with relative direction moves (.right()/.down()
    .length(...)) rather than absolute .to(target) — some two-terminal
    elements (e.g. SourceV) resolve .to() against their own default polarity
    direction rather than the literal target point, which silently collapses
    the element to zero-length. .at() is only used to (re)seat the pen at the
    start of a new branch.
    """
    nodes = spec["nodes"]
    horizontals = spec.get("horizontals", [])
    verticals = spec.get("verticals", [])

    node_x = {n: i * NODE_SPACING for i, n in enumerate(nodes)}
    top_y = 0.0

    verticals_by_node: dict[str, list[dict]] = {}
    for v in verticals:
        verticals_by_node.setdefault(v["at"], []).append(v)

    branch_xs: list[float] = []
    for node, branches in verticals_by_node.items():
        branch_xs.extend(_branch_x_positions(node_x[node], len(branches)))

    max_chain = max((len(v["elements"]) for v in verticals), default=1)
    ground_y = top_y - max_chain * BRANCH_HEIGHT - GROUND_MARGIN
    left_x = min([*node_x.values(), *branch_xs])
    right_x = max([*node_x.values(), *branch_xs])

    d = schemdraw.Drawing()

    # Invisible corner anchors, added identically in every stage, so all
    # three stages share the exact same bounding box regardless of how far
    # labels overflow the wire geometry. Without this, schemdraw's
    # auto-crop makes the labelled stage's canvas larger than the wires
    # stage's, and crossfading between differently-cropped/scaled images
    # reads as a visible double-image jump.
    pad_left, pad_right, pad_top, pad_bottom = 1.3, 1.3, 1.0, 1.1
    d += elm.Dot(radius=0).at((left_x - pad_left, top_y + pad_top)).color("white")
    d += elm.Dot(radius=0).at((right_x + pad_right, ground_y - pad_bottom)).color("white")

    for a, b in zip(nodes, nodes[1:]):
        h = next((h for h in horizontals if h["from"] == a and h["to"] == b), None)
        x1, x2 = node_x[a], node_x[b]
        cls = elm.Line if (h is None or stage == "wires") else _ELEMENT_TYPES[h["type"]]
        el = cls().at((x1, top_y)).right().length(x2 - x1)
        if stage == "labelled" and h is not None and h.get("value"):
            el = el.label(h["value"], loc="top")
        d += el

    for node, branches in verticals_by_node.items():
        nx = node_x[node]
        xs = _branch_x_positions(nx, len(branches))
        for bx, branch in zip(xs, branches):
            if bx != nx:
                jumper = elm.Line().at((nx, top_y))
                jumper = jumper.right().length(bx - nx) if bx > nx else jumper.left().length(nx - bx)
                d += jumper
            n_elements = len(branch["elements"])
            for i, element in enumerate(branch["elements"]):
                cls = elm.Line if stage == "wires" else _ELEMENT_TYPES[element["type"]]
                el = cls().at((bx, top_y)) if i == 0 else cls()
                el = el.down().length(BRANCH_HEIGHT)
                if stage == "labelled" and element.get("value") and cls is not elm.Line:
                    loc = "left" if bx <= nx else "right"
                    el = el.label(element["value"], loc=loc)
                d += el
            branch_bottom_y = top_y - n_elements * BRANCH_HEIGHT
            remainder = branch_bottom_y - ground_y
            if remainder > 1e-6:
                gnd_wire = elm.Line() if n_elements else elm.Line().at((bx, top_y))
                d += gnd_wire.down().length(remainder)

    d += elm.Line().at((left_x, ground_y)).right().length(right_x - left_x)
    if stage == "labelled":
        d += elm.Dot().at((right_x, ground_y)).label("0V", loc="bottom")
    return d


def render_circuit_stages(spec: dict, out_dir: str | Path, prefix: str = "circuit") -> list[str]:
    """Render the wires -> components -> labelled progression. Returns SVG paths in
    order (the composition's <img> tags load SVG natively, so there's no need to rasterize)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, stage in enumerate(["wires", "components", "labelled"]):
        d = _draw_circuit(spec, stage)
        path = out_dir / f"{prefix}_{i}_{stage}.svg"
        d.save(str(path))
        paths.append(str(path))
    return paths


def render_molecule(smiles: str, out_dir: str | Path, name: str = "molecule") -> str:
    """Generate a 2D structure SVG from a SMILES string via RDKit."""
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"could not parse SMILES: {smiles}")
    drawer = rdMolDraw2D.MolDraw2DCairo(640, 480)
    drawer.DrawMolecule(mol)
    drawer.FinishDrawing()
    path = out_dir / f"{name}.png"
    path.write_bytes(drawer.GetDrawingText())
    return str(path)
