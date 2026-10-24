import {
  Background, BackgroundVariant, Controls, type Edge, Handle, type Node, type NodeProps, Position, ReactFlow, useReactFlow, useStore,
} from "@xyflow/react";
import { memo, useEffect, useMemo } from "react";
import { layout, moveNumberLabel, pathTo, ROOT, scoreLabel, type Tree, type TreeNode, visibleChildren } from "../model";

type MoveNodeData = { node: TreeNode; current: boolean; onPath: boolean };

// The dot says where a move comes from; weaker and poor ones also get a dashed outline.
const DOT: Record<string, string> = {
  book: "bg-book",
  reference: "bg-reference",
  good: "bg-accent",
  weaker: "bg-weaker",
  poor: "bg-poor",
  explored: "bg-muted",
};
const OUTLINE: Record<string, string> = {
  weaker: "border-dashed border-weaker/60",
  poor: "border-dashed border-poor/60",
  explored: "border-dotted border-muted/60",
};

const MoveNode = memo(function MoveNode({ data }: NodeProps<Node<MoveNodeData>>) {
  const { node, current, onPath } = data;
  const move = node.move;
  const quality = move?.quality ?? "book";
  const frame = current
    ? "border-accent bg-accent/20 text-strong shadow-[0_0_0_4px_rgb(109_140_255/0.18),0_8px_24px_rgb(0_0_0/0.45)]"
    : `${OUTLINE[quality] ?? (onPath ? "border-accent/40" : "border-line")} ${onPath ? "bg-raised text-strong" : "bg-panel text-text"} shadow-[0_4px_14px_rgb(0_0_0/0.35)] hover:border-accent/60`;
  const score = scoreLabel(node);
  return (
    <div
      className={`w-[76px] cursor-pointer rounded-xl border px-2 py-1.5 transition-colors ${frame}`}
      title={move ? (move.lines.length ? move.lines.join(", ") : move.reference ? "Named variation, not researched yet" : undefined) : undefined}
    >
      <Handle type="target" position={Position.Top} className="!opacity-0" />
      {move ? (
        <>
          <div className="flex items-center justify-between text-[10px] leading-none text-muted">
            <span>{moveNumberLabel(node)}</span>
            <span className={`h-1.5 w-1.5 rounded-full ${DOT[quality]}`} aria-label={quality} />
          </div>
          <div className="mt-0.5 font-mono text-[13px] font-semibold leading-tight">{move.san}</div>
          <div className={`mt-0.5 text-[10px] leading-none tabular-nums ${quality === "weaker" ? "text-weaker" : quality === "poor" ? "text-poor" : "text-muted"}`}>
            {score || " "}
          </div>
        </>
      ) : (
        <div className="py-1.5 text-center text-xs font-medium text-strong">Start</div>
      )}
      <Handle type="source" position={Position.Bottom} className="!opacity-0" />
    </div>
  );
});

const nodeTypes = { move: MoveNode };
const NODE_W = 76;
const NODE_H = 52;

interface Props {
  tree: Tree;
  current: string;
  showWeaker: boolean;
  onSelect: (id: string) => void;
}

export function TreeView({ tree, current, showWeaker, onSelect }: Props) {
  const flow = useReactFlow();
  const path = useMemo(() => new Set(pathTo(current)), [current]);
  const placed = useMemo(() => layout(tree, showWeaker, current), [tree, showWeaker, current]);

  const nodes: Node<MoveNodeData>[] = placed.map(({ node, x, y }) => ({
    id: node.id || "start",
    type: "move",
    position: { x, y },
    data: { node, current: node.id === current, onPath: path.has(node.id) },
    draggable: false,
    connectable: false,
  }));
  const edges: Edge[] = placed
    .filter(({ node }) => node.parent !== null)
    .map(({ node }) => {
      const quality = node.move?.quality ?? "book";
      const stroke = path.has(node.id) ? "#6d8cff" : quality === "weaker" ? "#f5b14c99" : quality === "poor" ? "#f8717199" : "#3a4150";
      return {
        id: `e:${node.id}`,
        source: node.parent || "start",
        target: node.id,
        type: "smoothstep",
        pathOptions: { borderRadius: 14 },
        style: { stroke, strokeWidth: path.has(node.id) ? 2.25 : 1.25, strokeDasharray: quality === "weaker" || quality === "poor" ? "5 4" : undefined },
      };
    });

  // Keep the camera on the neighborhood: the parent, the current move and its alternatives,
  // and the next moves.
  // The layout already knows where every node is, so aim the viewport directly (no waiting
  // for React Flow to measure), and animate it so the eye can follow.
  const width = useStore((state) => state.width);
  const height = useStore((state) => state.height);
  const focusBox = useMemo(() => {
    const node = tree[current];
    const ids = new Set([current, ...visibleChildren(tree, current, showWeaker, path).map((c) => c.id)]);
    if (node?.parent !== null && node?.parent !== undefined) {
      ids.add(node.parent);
      // Siblings too: the other moves at this ply are the lines you can switch to.
      for (const sibling of visibleChildren(tree, node.parent, showWeaker, path)) ids.add(sibling.id);
    }
    const points = placed.filter((p) => ids.has(p.node.id));
    if (!points.length) return null;
    const xs = points.map((p) => p.x), ys = points.map((p) => p.y);
    return { x0: Math.min(...xs), x1: Math.max(...xs) + NODE_W, y0: Math.min(...ys), y1: Math.max(...ys) + NODE_H };
  }, [tree, current, showWeaker, path, placed]);
  useEffect(() => {
    if (!focusBox || !width || !height) return;
    const pad = 80;
    const zoom = Math.min(1.3, width / (focusBox.x1 - focusBox.x0 + pad * 2), height / (focusBox.y1 - focusBox.y0 + pad * 2));
    const cx = (focusBox.x0 + focusBox.x1) / 2, cy = (focusBox.y0 + focusBox.y1) / 2;
    void flow.setViewport({ x: width / 2 - cx * zoom, y: height / 2 - cy * zoom, zoom }, { duration: 450 });
  }, [flow, focusBox, width, height]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={(_, n) => onSelect(n.id === "start" ? ROOT : n.id)}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      minZoom={0.15}
      maxZoom={2}
      proOptions={{ hideAttribution: false }}
      colorMode="dark"
    >
      <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="#2a2f3a" />
      <Controls position="bottom-right" showInteractive={false} />
    </ReactFlow>
  );
}
