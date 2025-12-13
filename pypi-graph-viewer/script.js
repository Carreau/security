    const g = svg.append("g");

    // Function to draw a pentagon
    function drawPentagon(radius) {
        const sides = 5;
        const angle = Math.PI * 2 / sides;
        let path = "";
        for (let i = 0; i < sides; i++) {
            const x = radius * Math.sin(i * angle);
            const y = -radius * Math.cos(i * angle);
            if (i === 0) path += `M ${x} ${y}`;
            else path += `L ${x} ${y}`;
        }
        path += "Z";
        return path;
    }

    // Custom color function based on node properties
    function getNodeColor(d) {
        if (d.type === 'user') {
            return '#1f77b4'; // Blue for users
        } else if (d.type === 'org') {
            return '#9467bd'; // Purple for organizations
        } else if (d.type === 'package') {
            if (d.fetch_status === 'unfetched' || d.fetch_status === 'error' || d.fetch_status === 'not_found') {
                return '#8c8c8c'; // Grey for unfetched/error/not found packages
            } else if (d.maintainer_count === 0) {
                return '#d62728'; // Red for packages with 0 maintainers
            } else if (d.maintainer_count === 1) {
                return '#ff7f0e'; // Orange for packages with 1 maintainer
            } else {
                return '#2ca02c'; // Green for packages with >1 maintainer
            }
        }
        return '#000'; // Default black
    }

    const simulation = d3.forceSimulation()
        .force("link", d3.forceLink().id(d => d.id).distance(50))
        .force("charge", d3.forceManyBody().strength(-300))
        .force("center", d3.forceCenter(width / 2, height / 2));

    // Legend Data
    const legendData = [
        { label: 'User', type: 'user' },
        { label: 'Organization', type: 'org' }, // Type 'org' will be pentagon
        { label: 'Package (>1 Maintainer)', type: 'package', maintainer_count: 2, fetch_status: 'fetched' },
        { label: 'Package (1 Maintainer)', type: 'package', maintainer_count: 1, fetch_status: 'fetched' },
        { label: 'Package (0 Maintainers)', type: 'package', maintainer_count: 0, fetch_status: 'fetched' },
        { label: 'Package (Unfetched/Error)', type: 'package', maintainer_count: null, fetch_status: 'unfetched' }
    ];

    // Create Legend Group
    const legend = svg.append("g")
        .attr("class", "legend")
        .attr("transform", `translate(${width - 200}, 20)`); // Position at top right

    legend.selectAll("g.legend-item")
        .data(legendData)
        .enter().append("g")
        .attr("class", "legend-item")
        .attr("transform", (d, i) => `translate(0, ${i * 20})`)
        .each(function(d) {
            if (d.type === 'org') {
                d3.select(this).append("path")
                    .attr("d", drawPentagon(7)) // Pentagon for orgs in legend
                    .attr("fill", getNodeColor(d));
            } else {
                d3.select(this).append("circle")
                    .attr("r", 7)
                    .attr("fill", getNodeColor(d));
            }
        });

    legend.selectAll("g.legend-item")
        .append("text")
        .attr("x", 15)
        .attr("y", 5)
        .text(d => d.label)
        .style("font-size", "12px")
        .style("fill", "#333");

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
                .data(displayNodes, d => d.id);
            
            node.exit().remove();

            const nodeEnter = node.enter().append("g")
                .attr("class", "node");
            
            nodeEnter.each(function(d) {
                if (d.type === 'org') {
                    d3.select(this).append("path")
                        .attr("d", drawPentagon(10)) // 10 is radius
                        .attr("fill", getNodeColor(d)); // Use getNodeColor(d)
                } else {
                    d3.select(this).append("circle")
                        .attr("r", 10)
                        .attr("fill", getNodeColor(d)); // Use getNodeColor(d)
                }
            });

            nodeEnter.append("text")
                .text(d => d.name)
                .attr("x", 12)
                .attr("y", 3);
                
            nodeEnter.append("title")
                .text(d => `${d.type}: ${d.name}`);

            // Merge enter and update selections
            const nodeUpdate = nodeEnter.merge(node);

            nodeUpdate
                .call(drag(simulation))
                .on('click', toggleNode);

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
