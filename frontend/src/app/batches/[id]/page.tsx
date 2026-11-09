"use client";

import { useParams } from "next/navigation";
import { BatchView } from "@/components/BatchView";

export default function BatchPage() {
  const { id } = useParams<{ id: string }>();
  return <BatchView id={id} />;
}
