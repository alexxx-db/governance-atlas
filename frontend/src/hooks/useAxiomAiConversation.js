import { useCallback, useEffect, useRef, useState } from "react";
import { fetchAxiomAiRecommendations } from "../lib/api";

function evidenceCount(response) {
  return Array.isArray(response?.evidence) ? response.evidence.length : 0;
}

function splitTableRow(line) {
  const trimmed = String(line || "").trim();
  if (!trimmed.startsWith("|") || !trimmed.endsWith("|")) return null;
  return trimmed
    .slice(1, -1)
    .split("|")
    .map((cell) => cell.trim());
}

function markdownTablesToLists(text) {
  const lines = String(text || "").split("\n");
  const output = [];
  for (let index = 0; index < lines.length; index += 1) {
    const headers = splitTableRow(lines[index]);
    const separator = splitTableRow(lines[index + 1] || "");
    const isSeparator = separator?.every((cell) => /^:?-{3,}:?$/.test(cell));
    if (!headers || !isSeparator) {
      output.push(lines[index]);
      continue;
    }
    index += 1;
    while (index + 1 < lines.length) {
      const cells = splitTableRow(lines[index + 1]);
      if (!cells) break;
      const detail = headers
        .map((header, cellIndex) => `${header}: ${cells[cellIndex] || ""}`)
        .join("; ");
      output.push(`- ${detail}`);
      index += 1;
    }
  }
  return output.join("\n");
}

function normalizeAnswer(response) {
  const answer = String(response?.answer || "").trim();
  if (!answer) return "Axiom AI did not return an answer for that question.";
  const cleaned = answer
    .replace(/^Genie said[:,]?\s*/i, "")
    .replace(/^Genie returned (\d+) governed evidence rows?/i, "Found $1 governed evidence rows")
    .replace(/^Genie generated a governed SQL answer\.\s*/i, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return markdownTablesToLists(cleaned);
}

export function useAxiomAiConversation({ request = fetchAxiomAiRecommendations } = {}) {
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const requestSeqRef = useRef(0);
  const abortRef = useRef(null);

  useEffect(() => () => {
    abortRef.current?.abort?.();
  }, []);

  const ask = useCallback(async (question, context) => {
    const resolvedQuestion = String(question || draft || "").trim();
    if (!resolvedQuestion || loading) return null;

    abortRef.current?.abort?.();
    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    abortRef.current = controller;
    const requestSeq = requestSeqRef.current + 1;
    requestSeqRef.current = requestSeq;
    const userMessageId = `axiom-user-${requestSeq}`;
    const assistantMessageId = `axiom-assistant-${requestSeq}`;

    setDraft(resolvedQuestion);
    setError("");
    setLoading(true);
    setMessages((current) => [
      ...current,
      { id: userMessageId, role: "user", text: resolvedQuestion },
      {
        id: assistantMessageId,
        role: "assistant",
        text: "Checking governed metadata...",
        pending: true,
        stage: "",
      },
    ]);

    // Live Genie progress: the request layer calls this as the real pipeline
    // stage advances ("Selecting relevant tables" → "Generating the SQL query"
    // → "Running the query"), so the dock shows what's happening instead of a
    // canned animation while the answer streams.
    const onStage = (stage) => {
      if (requestSeqRef.current !== requestSeq) return;
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantMessageId ? { ...message, stage: String(stage || "") } : message,
        ),
      );
    };

    try {
      const response = await request(resolvedQuestion, {
        ...(controller ? { signal: controller.signal } : {}),
        ...(context ? { context } : {}),
        onStage,
      });
      if (requestSeqRef.current !== requestSeq) return response;
      // Surface a genuine failure (Genie FAILED / unavailable) as an error with
      // its reason, instead of collapsing to the bland "did not return an
      // answer" — the user must be able to tell a crash from an empty result.
      const rawAnswer = String(response?.answer || "").trim();
      const warnings = Array.isArray(response?.warnings)
        ? response.warnings
        : Array.isArray(response?.meta?.warnings)
          ? response.meta.warnings
          : [];
      const failureNote = response?.warning || warnings.find(Boolean) || "";
      const isFailure =
        (response?.intent === "unavailable" || response?.nonAuthoritative) && !rawAnswer && Boolean(failureNote);
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantMessageId
            ? {
                ...message,
                text: isFailure ? failureNote : normalizeAnswer(response),
                pending: false,
                error: isFailure || undefined,
                evidenceCount: evidenceCount(response),
                response,
              }
            : message,
        ),
      );
      setDraft("");
      return response;
    } catch (caught) {
      if (caught?.name === "AbortError" || requestSeqRef.current !== requestSeq) {
        return null;
      }
      const nextError = caught?.message || "Axiom AI recommendations are unavailable.";
      setError(nextError);
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantMessageId
            ? {
                ...message,
                text: nextError,
                pending: false,
                error: true,
              }
            : message,
        ),
      );
      return null;
    } finally {
      if (requestSeqRef.current === requestSeq) setLoading(false);
    }
  }, [draft, loading, request]);

  const reset = useCallback(() => {
    abortRef.current?.abort?.();
    requestSeqRef.current += 1;
    setDraft("");
    setMessages([]);
    setLoading(false);
    setError("");
  }, []);

  return {
    ask,
    draft,
    error,
    loading,
    messages,
    reset,
    setDraft,
  };
}

export default useAxiomAiConversation;
