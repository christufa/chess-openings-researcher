import { type Edge, Handle, type Node, type NodeProps, Position, ReactFlow, useReactFlow, useStore } from "@xyflow/react";
import { memo, useEffect, useMemo } from "react";
import { BookIcon } from "./BookIcon";
import { layout, moveNumberLabel, pathTo, ROOT, scoreLabel, type Tree, type TreeNode, visibleChildren } from "../model";

type MoveNodeData = { node: TreeNode; current: boolean; onPath: boolean };

const RING: Record<string, string> = {
  book: "border-book",
  reference: "border-reference",
  good: "border-line",
  weaker: "border-weaker border-dashed",
  poor: "border-poor border-dashed",
  explored: "border-muted border-dotted",
};

const MoveNode = memo(function MoveNode({ data }: NodeProps<Node<MoveNodeData>>) {
  const { node, current, onPath } = data;
  const move = node.move;
  const quality = move?.quality ?? "book";
  const base = current
    ? "border-accent bg-accent/15 text-strong ring-2 ring-accent/40"
    : `${RING[quality]} ${onPath ? "bg-raised text-strong" : "bg-panel"}`;
  return (
    <div
      className={`w-[72px] rounded-lg border px-2 py-1 text-center ${base}`}
      title={move ? (move.lines.length ? move.lines.join(", ") : move.reference ? "Named variation, not researched yet" : undefined) : undefined}
    >
      <Handle type="target" position={Position.Top} className="!opacity-0" />
      {move ? (
        <>
          <div className="text-[10px] leading-none text-muted">{moveNumberLabel(node)}</div>
          <div className="flex items-center justify-center gap-1 font-mono text-sm leading-tight">
            {move.book && <BookIcon className="text-book" />}
            {move.san}
          </div>
          <div className={`text-[10px] leading-none ${quality === "weaker" ? "text-weaker" : quality === "poor" ? "text-poor" : "text-muted"}`}>
            {scoreLabel(node) || " "}
          </div>
        </>
      ) : (
        <div className="py-1 text-xs text-strong">Start</div>
      )}
      <Handle type="source" position={Position.Bottom} className="!opacity-0" />
    </div>
  );
});

const nodeTypes = { move: MoveNode };
const NODE_W = 72;
const NODE_H = 46;

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
      const stroke = path.has(node.id) ? "#3692e7" : quality === "weaker" ? "#d59020" : quality === "poor" ? "#d64f4f" : "#5c5a57";
      return {
        id: `e:${node.id}`,
        source: node.parent || "start",
        target: node.id,
        type: "smoothstep",
        style: { stroke, strokeWidth: path.has(node.id) ? 2 : 1, strokeDasharray: quality === "weaker" || quality === "poor" ? "5 4" : undefined },
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
    />
  );
}
