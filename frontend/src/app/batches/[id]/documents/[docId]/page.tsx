"use client";

import { useParams } from "next/navigation";
import { ReviewView } from "@/components/review/ReviewView";

export default function ReviewPage() {
  const { id, docId } = useParams<{ id: string; docId: string }>();
  // Keyed by document, so moving to the next one starts with fresh state.
  return <ReviewView key={docId} batchId={id} docId={docId} />;
}
