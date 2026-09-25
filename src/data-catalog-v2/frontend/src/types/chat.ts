export interface ChatMessageData {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  sql?: string;
  mode: "metadata" | "agent";
}

export interface ChatResponse {
  session_id: string;
  message: ChatMessageData;
}

export interface ChatHistoryResponse {
  session_id: string;
  mode: string;
  messages: ChatMessageData[];
}
