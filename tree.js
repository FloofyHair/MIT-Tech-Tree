function parsePrereqs(txt) {
    if (!txt) return [];
    const matches = txt.match(/\b\d{1,2}\.\d+[A-Z]*\b/g);
    return matches || [];
}

function nodeId(code) {
    return code.replace(/\./g, '_');
}

function buildGraph(data) {
    const g = new dagreD3.graphlib.Graph().setGraph({ ranksep: 50, nodesep: 30, edgesep: 20 });
    const courseMap = {};

    Object.values(data).forEach(c => {
        const id = nodeId(c.code);
        courseMap[id] = c;
        g.setNode(id, { label: c.code });
    });

    Object.values(data).forEach(c => {
        const target = nodeId(c.code);
        parsePrereqs(c.prereq_text).forEach(pr => {
            const source = nodeId(pr);
            if (courseMap[source]) {
                g.setEdge(source, target, {});
            }
        });
    });

    const render = new dagreD3.render();
    const svg = d3.select('#tree');
    const svgGroup = svg.append('g');
    render(svgGroup, g);

    svg.attr('width', g.graph().width + 40);
    svg.attr('height', g.graph().height + 40);
    svgGroup.attr('transform', 'translate(20,20)');

    svgGroup.selectAll('g.node').each(function(id) {
        const color = courseMap[id].color || '#f9f9f9';
        d3.select(this).select('rect').style('--node-color', color);
    });

    svgGroup.selectAll('g.node')
        .on('mouseover', function(event, id) {
            d3.select(this).classed('active', true);
            const prereqs = parsePrereqs(courseMap[id].prereq_text);
            prereqs.forEach(pr => {
                const pid = nodeId(pr);
                svgGroup.select(`#${pid}`).classed('active', true);
            });
        })
        .on('mouseout', function() {
            svgGroup.selectAll('g.node').classed('active', false);
        });
}

fetch('classes.json')
    .then(r => r.json())
    .then(buildGraph)
    .catch(err => {
        d3.select('body').append('p').text('Failed to load classes.json: ' + err);
    });
