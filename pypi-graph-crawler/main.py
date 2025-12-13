import asyncio
import json
import pathlib
from typing import Optional, List, Dict, Any, Set, Tuple

import typer
from crawler import get_packages_for_entity, get_maintainers_for_package

app = typer.Typer(help="Crawl PyPI to build a graph of maintainers and packages.")

def save_graph(nodes: List[Dict[str, Any]], links: List[Dict[str, Any]], output_file: str):
    """Saves the graph data to a JSON file."""
    graph_data = {"nodes": nodes, "links": links}
    pathlib.Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(graph_data, f, indent=2)
    print(f"Graph data with {len(nodes)} nodes and {len(links)} links saved to: {output_file}")

async def main_async(
    user: Optional[str],
    org: Optional[str],
    depth: int,
    output_file: str,
    batch_size: int,
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

    current_level_queue: List[Tuple[str, str]] = [(start_node_name, start_type)]
    visited: Set[Tuple[str, str]] = set()

    def add_node(name, type, maintainer_count=None, fetch_status=None):
        if (name, type) not in node_set:
            node_data = {"id": f"{type}:{name}", "name": name, "type": type}
            if type == "package":
                node_data["maintainer_count"] = maintainer_count
                node_data["fetch_status"] = fetch_status
            nodes.append(node_data)
            node_set.add((name, type))

    def add_link(source_name, source_type, target_name, target_type):
        source_id = f"{source_type}:{source_name}"
        target_id = f"{target_type}:{target_name}"
        if not any(l['source'] == source_id and l['target'] == target_id for l in links):
            links.append({"source": source_id, "target": target_id})

    for current_depth in range(depth + 1):
        print(f"\nProcessing depth {current_depth} with {len(current_level_queue)} entities...")
        next_level_queue = []

        for i in range(0, len(current_level_queue), batch_size):
            batch = current_level_queue[i:i+batch_size]
            tasks = []
            
            # Entities to process in the current batch
            entities_to_process = []

            for name, type in batch:
                if (name, type) in visited:
                    continue
                
                # For packages, we need to add them with initial maintainer info
                if type == "package":
                    # Mark as 'unfetched' initially, will be updated after actual fetch
                    add_node(name, type, maintainer_count=0, fetch_status="unfetched")
                else:
                    add_node(name, type)
                visited.add((name, type))
                
                entities_to_process.append((name, type))

                if type in ["user", "org"]:
                    tasks.append(get_packages_for_entity(name, type))
                elif type == "package":
                    tasks.append(get_maintainers_for_package(name))

            results = await asyncio.gather(*tasks)

            for idx, ((name, type), result_items) in enumerate(zip(entities_to_process, results)):
                if type in ["user", "org"]:
                    for package_name in result_items:
                        add_node(package_name, "package", maintainer_count=0, fetch_status="unfetched") # Add with initial status
                        add_link(name, type, package_name, "package")
                        if (package_name, "package") not in visited:
                            next_level_queue.append((package_name, "package"))
                elif type == "package":
                    maintainers, maintainer_count, fetch_status = result_items
                    
                    # Update the node's maintainer info after fetching
                    for node_item in nodes:
                        if node_item["id"] == f"package:{name}":
                            node_item["maintainer_count"] = maintainer_count
                            node_item["fetch_status"] = fetch_status
                            break

                    if fetch_status == 'fetched' and maintainers: # Only proceed if maintainers were actually found
                        orgs_for_package = [m for m in maintainers if m['type'] == 'org']
                        users_for_package = [m for m in maintainers if m['type'] == 'user']

                        # Logic for linking packages and maintainers
                        if orgs_for_package:
                            # Link package to orgs
                            for org_data in orgs_for_package:
                                org_name = org_data['name']
                                add_node(org_name, 'org')
                                add_link(name, type, org_name, 'org') # Package -> Org
                                if (org_name, 'org') not in visited:
                                    next_level_queue.append((org_name, 'org'))
                            
                            # Link user maintainers to orgs, not directly to package
                            for user_data in users_for_package:
                                user_name = user_data['name']
                                add_node(user_name, 'user')
                                for org_data in orgs_for_package: # Link user to each org of the package
                                    org_name = org_data['name']
                                    add_link(user_name, 'user', org_name, 'org') # User -> Org
                                if (user_name, 'user') not in visited:
                                    next_level_queue.append((user_name, 'user'))
                        else:
                            # If no orgs, link user maintainers directly to package
                            for maintainer in maintainers: # These will primarily be users if no orgs
                                m_name, m_type = maintainer['name'], maintainer['type']
                                add_node(m_name, m_type)
                                add_link(name, type, m_name, m_type) # Package -> Maintainer
                                if (m_name, m_type) not in visited:
                                    next_level_queue.append((m_name, m_type))
                    
                    # Always save after processing a package's maintainers, regardless of count
                    save_graph(nodes, links, output_file) 
        
        current_level_queue = next_level_queue

    print(f"\nCrawl complete.")

@app.command()
def main_cli(
    user: Optional[str] = typer.Option(None, "--user", help="The initial user to start crawling from."),
    org: Optional[str] = typer.Option(None, "--org", help="The initial organization to start crawling from."),
    depth: int = typer.Option(3, "--depth", help="The maximum depth to crawl."),
    output_file: str = typer.Option("pypi-graph-viewer/graph.json", "--output", help="The output file for the graph data."),
    batch_size: int = typer.Option(10, "--batch-size", help="Number of concurrent requests to make."),
):
    """Wrapper to run the async main function."""
    asyncio.run(main_async(user, org, depth, output_file, batch_size))

if __name__ == "__main__":
    app()