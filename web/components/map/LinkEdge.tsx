"use client";
// A relationship between two devices: right-angled like a wiring diagram, styled by kind (see kinds.ts), faded when
// either end is silent. Selected, it is drawn thicker; the map shows its kinds and a delete button in a bar below.
import { memo } from "react";
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, Position, useStore, type Edge, type EdgeProps } from "@xyflow/react";
import type { LinkKind } from "@/lib/types";
import { LINK } from "./kinds";

export type LinkEdgeData = { kind: LinkKind; faded: boolean };
export type LinkEdgeType = Edge<LinkEdgeData, "link">;

/** The arrowhead points into the target along the side the line arrives on. */
const ROT: Record<Position, number> = { [Position.Left]: 0, [Position.Top]: 90, [Position.Right]: 180, [Position.Bottom]: 270 };

function LinkEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, selected }:
  EdgeProps<LinkEdgeType>) {
  const k = LINK[data?.kind ?? "network"];
  const far = useStore((s) => s.transform[2] < 0.6); // labels too small to read: the key under the map says it
  const [path, lx, ly] = getSmoothStepPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition,
    borderRadius: 12 });
  const style = { stroke: k.color, strokeWidth: selected ? 3 : 2, strokeDasharray: k.dash,
    opacity: data?.faded ? 0.35 : 1 };
  return (
    <>
      <BaseEdge id={id} path={path} style={style} className={k.flow ? "edge-flow" : undefined} interactionWidth={18} />
      {k.arrow && (
        <path d="M -9 -5 L 0 0 L -9 5 z" style={{ fill: k.color, opacity: style.opacity }}
          transform={`translate(${targetX} ${targetY}) rotate(${ROT[targetPosition]})`} />)}
      <EdgeLabelRenderer>
        <div className={`elabel k-${data?.kind ?? "network"}`} style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` }}>
          {!far && <span className="everb">{k.verb}</span>}
        </div>
      </EdgeLabelRenderer>
    </>
  );
}

export default memo(LinkEdge);
