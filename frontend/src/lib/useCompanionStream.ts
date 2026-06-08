"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { wsBase } from "./api";
import { getToken } from "./auth";
import type { ClientMessage, StreamEvent } from "./types";
import { useGraphStore } from "@/store/graphStore";
import { useTranscriptStore } from "@/store/transcriptStore";

const GRAPH_EVENTS = new Set(["node.create", "node.update", "edge.create"]);

/**
 * Connects to WS /ws/companion/{checkoutId}, demuxes the event stream into the
 * graph + transcript stores, and auto-reconnects. State survives reconnects
 * because both stores persist per checkout (sessionStorage) — so the canvas and
 * transcript are restored, not lost.
 */
export function useCompanionStream(
  checkoutId: string,
  onSay?: (text: string) => void,
) {
  const [connected, setConnected] = useState(false);
  const [fatal, setFatal] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const closedRef = useRef(false);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 1008 = policy violation (bad/expired token, or the checkout no longer
  // exists). Permanent for this checkout — stop reconnecting and surface it,
  // rather than hammering a dead session forever.
  const WS_POLICY_VIOLATION = 1008;

  const applyGraph = useGraphStore((s) => s.apply);
  const applyTranscript = useTranscriptStore((s) => s.apply);
  const setBusy = useTranscriptStore((s) => s.setBusy);

  // Keep the latest onSay without re-subscribing the socket when it changes.
  const onSayRef = useRef(onSay);
  onSayRef.current = onSay;

  useEffect(() => {
    closedRef.current = false;

    const fail = (reason: string) => {
      closedRef.current = true; // stop the reconnect loop
      setConnected(false);
      setFatal(reason);
    };

    const connect = () => {
      const token = getToken();
      if (!token) return;
      const ws = new WebSocket(`${wsBase()}/ws/companion/${checkoutId}?token=${token}`);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onmessage = (e) => {
        let parsed: { type: string; data?: Record<string, unknown> };
        try {
          parsed = JSON.parse(e.data);
        } catch {
          return;
        }
        if (parsed.type === "error") {
          const reason =
            typeof parsed.data?.reason === "string"
              ? parsed.data.reason
              : "This session is no longer available.";
          fail(reason);
          return;
        }
        const ev = parsed as StreamEvent;
        if (GRAPH_EVENTS.has(ev.type)) applyGraph(ev);
        else applyTranscript(ev);
        // Speak live narration only (replay/restore goes through the store path,
        // never here — so resuming a session doesn't re-read the whole history).
        if (ev.type === "say") onSayRef.current?.(ev.data.text);
      };
      ws.onclose = (e) => {
        setConnected(false);
        if (e.code === WS_POLICY_VIOLATION) {
          fail("This session is no longer available.");
          return;
        }
        if (!closedRef.current) {
          retryRef.current = setTimeout(connect, 1500); // resubscribe; stores persist
        }
      };
      ws.onerror = () => ws.close();
    };

    connect();
    return () => {
      closedRef.current = true;
      if (retryRef.current) clearTimeout(retryRef.current);
      wsRef.current?.close();
    };
  }, [checkoutId, applyGraph, applyTranscript]);

  const send = useCallback((msg: ClientMessage) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  }, []);

  const sendSubject = useCallback(
    (text: string) => {
      setBusy(true);
      send({ type: "subject", text });
    },
    [send, setBusy],
  );
  const answer = useCallback((text: string) => send({ type: "answer", text }), [send]);
  const interrupt = useCallback((text: string) => send({ type: "interrupt", text }), [send]);
  const pullThread = useCallback(
    (nodeId: string) => {
      setBusy(true);
      send({ type: "pull_thread", node_id: nodeId });
    },
    [send, setBusy],
  );
  const exploreQuestion = useCallback(
    (nodeId: string) => {
      setBusy(true);
      send({ type: "explore_question", node_id: nodeId });
    },
    [send, setBusy],
  );
  const explain = useCallback(
    (nodeId: string) => {
      setBusy(true);
      send({ type: "explain", node_id: nodeId });
    },
    [send, setBusy],
  );

  return {
    connected,
    fatal,
    sendSubject,
    answer,
    interrupt,
    pullThread,
    exploreQuestion,
    explain,
  };
}
