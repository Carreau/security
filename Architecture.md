# PyPI Graph Crawler and Viewer Architecture

This document outlines the features and implementation details of the PyPI Graph application, which consists of a Python-based crawler for PyPI data and an interactive web-based graph viewer.

## 1. Application Features

### 1.1 PyPI Graph Crawler

The crawler is a command-line interface (CLI) tool designed to explore the PyPI ecosystem and build a network graph of packages, users, and organizations.

*   **Configurable Starting Points:** Users can initiate a crawl from a specified PyPI user (`--user <username>`) or organization (`--org <orgname>`).
*   **Depth Control:** The crawl depth (`--depth <integer>`) can be configured to limit how far the crawler explores the network from the initial starting point.
*   **Efficient Fetching:**
    *   Employs asynchronous HTTP requests (`httpx`) and concurrent batch processing (`--batch-size <integer>`) to make web requests to PyPI efficiently.
    *   Includes robust scraping logic with `Playwright` as a fallback mechanism to handle JavaScript-rendered pages and anti-scraping measures (like Fastly challenges) on PyPI.
*   **Intelligent Caching:** Implements a JSON-based caching system for fetched package lists and maintainer details, significantly reducing redundant network requests and speeding up subsequent crawls. Cache entries have a configurable time-to-live (TTL).
*   **Graph Data Generation:** Constructs a `graph.json` file in a D3.js-compatible format, containing:
    *   **Nodes:** Representing users, organizations, and packages, each with a unique ID, name, and type. Package nodes also include `maintainer_count` and `fetch_status` (e.g., 'fetched', 'unfetched', 'error', 'not_found').
    *   **Links:** Representing relationships between nodes (e.g., User -> Package, Package -> Org, Org -> Maintainer).
*   **Incremental Saving:** The `graph.json` file is saved periodically during the crawl (after each batch of package maintainer fetches), allowing users to view the evolving graph in real-time and providing resilience against interruptions.
*   **Refined Linking Logic:** Implements a specific rule for package-maintainer relationships: If a package is maintained by an organization, the package is linked to the organization, and individual maintainers are linked to the organization (not directly to the package). If no organization is involved, maintainers are linked directly to the package.

### 1.2 Interactive Graph Viewer

The viewer is a client-side web application that visualizes the `graph.json` data as an interactive force-directed network graph.

*   **Web-Based Visualization:** Displays the network graph within a web browser (HTML, CSS, JavaScript).
*   **Force-Directed Layout:** Utilizes D3.js's force simulation to arrange nodes and links dynamically, helping to illustrate clusters and relationships in the network.
*   **Dynamic Depth Control:** A slider on the page allows users to adjust the initial rendering depth of the graph, providing control over the initial complexity displayed.
*   **Expand/Collapse Interaction:** Clicking on a node dynamically expands or collapses its direct neighbors, enabling focused exploration of the network without overwhelming the user.
*   **Node Manipulation:** Users can drag and reposition individual nodes within the graph.
*   **Zoom and Pan:** Standard zoom and pan functionalities are available for navigating the graph canvas.
*   **Categorized Node Styling:**
    *   **Shapes:** Organization nodes are uniquely rendered as pentagons, while user and package nodes are circles.
    *   **Colors:** Nodes are color-coded to quickly identify their type and status:
        *   **Users:** Blue
        *   **Organizations:** Purple
        *   **Packages (>1 Maintainer):** Green
        *   **Packages (1 Maintainer):** Orange
        *   **Packages (0 Maintainers):** Red
        *   **Packages (Unfetched/Error/Not Found):** Grey
*   **Interactive Legend:** A visual legend is displayed on the graph canvas, explaining the meaning of each node shape and color.

## 2. Implementation Details

### 2.1 Project Structure

The project is structured into two main components within their respective directories:

*   `pypi-graph-crawler/`: Contains the Python CLI application (`main.py`, `crawler.py`).
*   `pypi-graph-viewer/`: Contains the client-side web application (`index.html`, `style.css`, `script.js`).

### 2.2 PyPI Graph Crawler Implementation

*   **Language & Frameworks:** Primarily written in Python.
    *   `typer`: Used for creating a robust and user-friendly command-line interface.
    *   `httpx`: An asynchronous HTTP client, enabling efficient concurrent web requests.
    *   `BeautifulSoup4`: Utilized for parsing the HTML content of PyPI pages to extract relevant data.
    *   `playwright`: Employed for automated browser control (headless Chromium) to render and scrape dynamically loaded content or bypass JavaScript challenges on PyPI.
    *   `asyncio`: Python's standard library for asynchronous programming, orchestrating concurrent operations (e.g., fetching multiple packages or maintainer lists in parallel).
*   **Caching Mechanism:** A custom, file-based JSON caching system stores fetched PyPI responses (`packages_<entity>.json`, `maintainers_<package>.json`) in `~/.cache/pypi_crawler/`. Cache entries include a timestamp and respect a configurable TTL to ensure data freshness while minimizing redundant API calls.
*   **Graph Traversal:** Implements a Breadth-First Search (BFS) algorithm to explore the PyPI network. It uses two queues (`current_level_queue`, `next_level_queue`) to process nodes level by level, ensuring that depth limits are respected.
*   **Concurrency:** Requests for packages and maintainers within each level are batched and executed concurrently using `asyncio.gather`.
*   **Data Handling:**
    *   The `add_node` and `add_link` helper functions manage the in-memory graph representation (lists of dictionaries for nodes and links).
    *   Package nodes are enriched with `maintainer_count` and `fetch_status` data, enabling the viewer's advanced coloring.
*   **Output:** The final (or intermediate) graph data is serialized to `pypi-graph-viewer/graph.json`.

### 2.3 Interactive Graph Viewer Implementation

*   **Frontend Technologies:**
    *   HTML5: Structures the web page, including the graph container, slider, and legend area.
    *   CSS3: Provides styling for the page layout and visual elements of the graph.
    *   JavaScript (ES6+): Powers the dynamic behavior, interactivity, and D3.js integration.
    *   D3.js (v7): The core library for binding data to DOM elements, creating the force-directed layout, and handling all graph rendering and interactions.
*   **Graph Rendering:**
    *   An SVG element is used as the canvas for the graph.
    *   D3's `forceSimulation` is configured with `forceLink`, `forceManyBody` (charge), and `forceCenter` to create an aesthetically pleasing and stable layout.
    *   Nodes are rendered as SVG `<circle>` elements (for users and packages) or `<path>` elements (for organizations, using a custom `drawPentagon` function).
    *   Links are rendered as SVG `<line>` elements.
*   **Interactivity:**
    *   **Drag:** D3's `drag` behavior allows users to reposition nodes.
    *   **Zoom/Pan:** D3's `zoom` behavior enables seamless navigation of the graph. Double-click zoom is explicitly disabled to prevent conflicts with node clicks.
    *   **Expand/Collapse:** A custom `toggleNode` function (triggered by node clicks) manages a `visibleNodes` Set, dynamically updating the D3 selections to show or hide neighbors. Event propagation is stopped to prevent accidental zooming.
    *   **Depth Slider:** An HTML range input (`<input type="range">`) updates the graph's initial display depth by calling `resetGraph`, which re-calculates `visibleNodes` and triggers an `update()`.
*   **Node Styling Logic:**
    *   A `getNodeColor(d)` function dynamically determines the fill color of each node based on its `type`, `maintainer_count`, and `fetch_status` properties from the loaded `graph.json`.
    *   A dedicated legend group is created in SVG, displaying sample shapes and colors corresponding to the defined node types and statuses.
*   **Data Flow:** The `script.js` loads `graph.json` asynchronously (`d3.json()`) and uses this data to drive all visualization and interaction logic.
