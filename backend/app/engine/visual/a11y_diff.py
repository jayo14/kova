from typing import Any


def _flatten_tree(node: dict | list | None) -> list[dict[str, Any]]:
    """Flatten an accessibility tree into a list of node dictionaries."""
    if not node:
        return []
    if isinstance(node, list):
        items: list[dict[str, Any]] = []
        for child in node:
            items.extend(_flatten_tree(child))
        return items

    result = [node]
    children = node.get("children") or []
    for child in children:
        result.extend(_flatten_tree(child))
    return result


def compute_a11y_diff(baseline_tree: dict | list, current_tree: dict | list) -> dict[str, Any]:
    """Compare accessibility trees for structural and semantic differences.

    Detects: missing elements, added elements, diff count.
    """
    baseline_nodes = _flatten_tree(baseline_tree)
    current_nodes = _flatten_tree(current_tree)

    def _node_key(n: dict) -> tuple[str, str]:
        role = str(n.get("role") or "").strip()
        name = str(n.get("name") or n.get("title") or n.get("text") or "").strip()
        return (role, name)

    baseline_keys = {_node_key(n) for n in baseline_nodes if _node_key(n) != ("", "")}
    current_keys = {_node_key(n) for n in current_nodes if _node_key(n) != ("", "")}

    missing = baseline_keys - current_keys
    added = current_keys - baseline_keys

    missing_elements = [{"role": role, "name": name} for role, name in missing]
    added_elements = [{"role": role, "name": name} for role, name in added]

    return {
        "missing_elements": missing_elements,
        "added_elements": added_elements,
        "diff_count": len(missing_elements) + len(added_elements),
    }
