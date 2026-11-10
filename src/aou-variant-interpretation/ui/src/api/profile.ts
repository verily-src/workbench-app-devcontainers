import { apiFetch } from "./client";

export interface UserProfile {
  userEmail: string;
}

export const fetchProfile = () => apiFetch<UserProfile>("/profile");
