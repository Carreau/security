document.addEventListener('DOMContentLoaded', () => {
    const container = document.getElementById('graph-container');
    const width = container.clientWidth;
    const height = container.clientHeight;
    const depthSlider = document.getElementById('depth-slider');
    const depthValue = document.getElementById('depth-value');

    const svg = d3.select(container).append("svg")
        .attr("width", width)
        .attr("height", height)
        .call(d3.zoom().on("zoom", (event) => {
            g.attr("transform", event.transform);
        }))
        .on("dblclick.zoom", null); // Disable double-click zoom

    const g = svg.append("g");

    const color = d3.scaleOrdinal(d3.schemeCategory10);

    const simulation = d3.forceSimulation()
        .force("link", d3.forceLink().id(d => d.id).distance(50))
        .force("charge", d3.forceManyBody().strength(-300))
        .force("center", d3.forceCenter(width / 2, height / 2));

    d3.json("graph.json").then(fullGraph => {
        let visibleNodes;

        function getInitialVisibleNodes(graph, startNodeId, depth) {
            const visible = new Set([startNodeId]);
            const queue = [[startNodeId, 0]];
            const visited = new Set([startNodeId]);

            while (queue.length > 0) {
                const [currentId, currentDepth] = queue.shift();

                if (currentDepth >= depth) {
                    continue;
                }

                graph.links.forEach(link => {
                    const sourceId = link.source.id || link.source;
                    const targetId = link.target.id || link.target;

                    if (sourceId === currentId && !visited.has(targetId)) {
                        visible.add(targetId);
                        visited.add(targetId);
                        queue.push([targetId, currentDepth + 1]);
                    } else if (targetId === currentId && !visited.has(sourceId)) {
                        visible.add(sourceId);
                        visited.add(sourceId);
                        queue.push([sourceId, currentDepth + 1]);
                    }
                });
            }
            return visible;
        }

        function resetGraph(depth) {
            if (fullGraph.nodes.length > 0) {
                const startNodeId = fullGraph.nodes[0].id;
                visibleNodes = getInitialVisibleNodes(fullGraph, startNodeId, depth);
            } else {
                visibleNodes = new Set();
            }
            update();
        }

        depthSlider.addEventListener('input', (event) => {
            const depth = parseInt(event.target.value, 10);
            depthValue.textContent = depth;
            resetGraph(depth);
        });

        resetGraph(parseInt(depthSlider.value, 10));

        function update() {
            const displayNodes = fullGraph.nodes.filter(d => visibleNodes.has(d.id));
            const displayLinks = fullGraph.links.filter(l => visibleNodes.has(l.source.id || l.source) && visibleNodes.has(l.target.id || l.target));

            g.selectAll(".link").remove();
            g.selectAll(".node").remove();

            const link = g.selectAll(".link")
                .data(displayLinks, d => `${d.source.id}-${d.target.id}`)
                .enter().append("line")
                .attr("class", "link");

            const node = g.selectAll(".node")
                .data(displayNodes, d => d.id)
                .enter().append("g")
                .attr("class", "node")
                .call(drag(simulation))
                .on('click', toggleNode);

            node.append("circle")
                .attr("r", 10)
                .attr("fill", d => color(d.type));

            node.append("text")
                .text(d => d.name)
                .attr("x", 12)
                .attr("y", 3);
                
            node.append("title")
                .text(d => `${d.type}: ${d.name}`);

            simulation
                .nodes(displayNodes)
                .on("tick", ticked);

            simulation.force("link")
                .links(displayLinks);
                
            simulation.alpha(1).restart();

            function ticked() {
                g.selectAll(".link")
                    .attr("x1", d => d.source.x)
                    .attr("y1", d => d.source.y)
                    .attr("x2", d => d.target.x)
                    .attr("y2", d => d.target.y);

                g.selectAll(".node")
                    .attr("transform", d => `translate(${d.x},${d.y})`);
            }
        }
        
        function toggleNode(event, d) {
            event.stopPropagation(); // Prevent zoom on click
            const neighbors = new Set();
            fullGraph.links.forEach(link => {
                const sourceId = link.source.id || link.source;
                const targetId = link.target.id || link.target;
                if (sourceId === d.id) neighbors.add(targetId);
                if (targetId === d.id) neighbors.add(sourceId);
            });

            let allNeighborsVisible = true;
            neighbors.forEach(neighborId => {
                if (!visibleNodes.has(neighborId)) {
                    allNeighborsVisible = false;
                }
            });

            if (allNeighborsVisible) {
                // Hide neighbors
                neighbors.forEach(neighborId => {
                    if (neighborId === fullGraph.nodes[0].id) return; // Never hide the root node

                    let isConnectedToOtherVisibleNode = false;
                    fullGraph.links.forEach(link => {
                        const sourceId = link.source.id || link.source;
                        const targetId = link.target.id || link.target;
                        if ((sourceId === neighborId && visibleNodes.has(targetId) && targetId !== d.id) ||
                            (targetId === neighborId && visibleNodes.has(sourceId) && sourceId !== d.id)) {
                            isConnectedToOtherVisibleNode = true;
                        }
                    });
                    if (!isConnectedToOtherVisibleNode) {
                        visibleNodes.delete(neighborId);
                    }
                });
            } else {
                // Show neighbors
                neighbors.forEach(neighborId => visibleNodes.add(neighborId));
            }
            
            update();
        }

    });

    function drag(simulation) {
        function dragstarted(event, d) {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        }

        function dragged(event, d) {
            d.fx = event.x;
            d.fy = event.y;
        }

        function dragended(event, d) {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        }

        return d3.drag()
            .on("start", dragstarted)
            .on("drag", dragged)
            .on("end", dragended);
    }
});
