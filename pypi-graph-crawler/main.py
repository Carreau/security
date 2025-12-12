
import typer
from typing import Optional

app = typer.Typer(help="Crawl PyPI to build a graph of maintainers and packages.")

import asyncio
import pathlib
import json
import typer
from typing import Optional, List, Dict, Any, Set, Tuple

from crawler import get_packages_for_entity, get_maintainers_for_package

app = typer.Typer(help="Crawl PyPI to build a graph of maintainers and packages.")

async def main_async(
    user: Optional[str] = typer.Option(None, "--user", help="The initial user to start crawling from."),
    org: Optional[str] = typer.Option(None, "--org", help="The initial organization to start crawling from."),
    depth: int = typer.Option(2, "--depth", help="The maximum depth to crawl."),
    output_file: str = typer.Option("../pypi-graph-viewer/graph.json", "--output", help="The output file for the graph data."),
):
    """
    Crawls PyPI to build a graph of maintainers and packages,
    starting from a given user or organization.
    """
    if not user and not org:
        print("Error: Please provide either a --user or an --org to start crawling.")
        raise typer.Exit(code=1)

    if user and org:
        print("Error: Please provide either a --user or an --org, not both.")
        raise typer.Exit(code=1)

    start_node_name = user if user else org
    start_type = "user" if user else "org"

    print(f"Starting crawl at {start_type}: {start_node_name}")
    print(f"Crawling to a depth of: {depth}")

    nodes: List[Dict[str, Any]] = []
    links: List[Dict[str, Any]] = []
    node_set: Set[Tuple[str, str]] = set()

    # Queue for BFS: (name, type, current_depth)
    queue: List[Tuple[str, str, int]] = [(start_node_name, start_type, 0)]
    visited: Set[Tuple[str, str]] = set()

    def add_node(name, type):
        if (name, type) not in node_set:
            nodes.append({"id": f"{type}:{name}", "name": name, "type": type})
            node_set.add((name, type))

    def add_link(source_name, source_type, target_name, target_type):
        source_id = f"{source_type}:{source_name}"
        target_id = f"{target_type}:{target_name}"
        # Avoid duplicate links
        if not any(l['source'] == source_id and l['target'] == target_id for l in links):
            links.append({"source": source_id, "target": target_id})

    while queue:
        current_name, current_type, current_depth = queue.pop(0)

        if (current_name, current_type) in visited or current_depth > depth:
            continue

        print(f"Processing {current_type} '{current_name}' at depth {current_depth}...")
        visited.add((current_name, current_type))
        add_node(current_name, current_type)

        if current_type in ["user", "org"]:
            packages = await get_packages_for_entity(current_name, current_type)
            for package_name in packages:
                add_node(package_name, "package")
                add_link(current_name, current_type, package_name, "package")
                if (package_name, "package") not in visited:
                    queue.append((package_name, "package", current_depth + 1))

        elif current_type == "package":
            maintainers = await get_maintainers_for_package(current_name)
            orgs_for_package = [m for m in maintainers if m['type'] == 'org']
            
            # If orgs are present, link package to orgs
            if orgs_for_package:
                for org_data in orgs_for_package:
                    org_name = org_data['name']
                    add_node(org_name, 'org')
                    add_link(current_name, current_type, org_name, 'org')
                    if (org_name, 'org') not in visited:
                        queue.append((org_name, 'org', current_depth + 1))
            
            # Link users directly to package, or to org if orgs are present
            for maintainer_data in maintainers:
                maintainer_name = maintainer_data['name']
                maintainer_type = maintainer_data['type']
                add_node(maintainer_name, maintainer_type)
                
                # If no orgs, link user directly to package
                if not orgs_for_package and maintainer_type == 'user':
                    add_link(current_name, current_type, maintainer_name, maintainer_type)

                if (maintainer_name, maintainer_type) not in visited:
                     queue.append((maintainer_name, maintainer_type, current_depth + 1))


    graph_data = {"nodes": nodes, "links": links}
    
    print(f"\nCrawl complete. Found {len(nodes)} nodes and {len(links)} links.")
    
    pathlib.Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(graph_data, f, indent=2)
        
    print(f"Graph data saved to: {output_file}")



@app.command()
def main_cli(
    user: Optional[str] = typer.Option(None, "--user", help="The initial user to start crawling from."),
    org: Optional[str] = typer.Option(None, "--org", help="The initial organization to start crawling from."),
    depth: int = typer.Option(2, "--depth", help="The maximum depth to crawl."),
    output_file: str = typer.Option("../pypi-graph-viewer/graph.json", "--output", help="The output file for the graph data."),
):
    """Wrapper to run the async main function."""
    asyncio.run(main_async(user, org, depth, output_file))

if __name__ == "__main__":
    app()
