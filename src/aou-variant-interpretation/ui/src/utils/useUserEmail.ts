import { useEffect, useState } from "react";
import { fetchProfile } from "../api/profile";

/** The signed-in user's email for the top bar; empty until the profile loads, or if it can't. */
export function useUserEmail(): string {
  const [userEmail, setUserEmail] = useState("");
  useEffect(() => {
    fetchProfile()
      .then((profile) => setUserEmail(profile.userEmail))
      .catch((err: Error) => console.error("Failed to load profile", err));
  }, []);
  return userEmail;
}
