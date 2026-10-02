"use client";

import { useReducer, useCallback } from "react";
import type {
  ExploreState,
  AgentActivityItem,
  DiscoveryItem,
  SuggestedMission,
  CredentialRequest,
  AgentQuestionItem,
} from "@/lib/types";

export interface ScreenshotEntry {
  id: string;
  url: string;
  timestamp: number;
  label?: string;
}

let _screenshotCounter = 0;

export interface ExploreMachineState {
  url: string;
  intent?: string;
  state: ExploreState;
  activities: AgentActivityItem[];
  discoveries: DiscoveryItem[];
  credentialRequest: CredentialRequest | null;
  authMode: AuthMode;
  question: AgentQuestionItem | null;
  missions: SuggestedMission[];
  recommendationNote?: string;
  selectedMissionIds: string[];
  error: string | null;
  createdProjectId: string | null;
  screenshots: ScreenshotEntry[];
  currentPath: string | null;
}

export type AuthMode = "choice" | "create_account" | "manual_login" | "creating_account";

export type ExploreAction =
  | { type: "START"; url: string; intent?: string }
  | { type: "TRANSITION"; state: ExploreState }
  | { type: "ADD_ACTIVITY"; activity: AgentActivityItem }
  | { type: "SET_AUTH_REQUIRED"; request: CredentialRequest }
  | { type: "SET_AUTH_MODE"; mode: AuthMode }
  | { type: "SET_QUESTION"; question: AgentQuestionItem }
  | { type: "SET_DISCOVERIES"; discoveries: DiscoveryItem[] }
  | { type: "SET_MISSIONS"; missions: SuggestedMission[]; recommendation?: string }
  | { type: "TOGGLE_MISSION"; id: string }
  | { type: "SELECT_ALL_MISSIONS" }
  | { type: "UPDATE_MISSION"; mission: SuggestedMission }
  | { type: "MISSION_CREATED"; projectId: string }
  | { type: "ADD_SCREENSHOT"; screenshot: string; label?: string }
  | { type: "SET_PAGE"; url: string; title?: string; path?: string; screenshot?: string }
  | { type: "FAIL"; error: string }
  | { type: "CANCEL" }
  | { type: "RESET" };

export const initialExploreState: ExploreMachineState = {
  url: "",
  intent: undefined,
  state: "idle",
  activities: [],
  discoveries: [],
  credentialRequest: null,
  authMode: "choice",
  question: null,
  missions: [],
  recommendationNote: undefined,
  selectedMissionIds: [],
  error: null,
  createdProjectId: null,
  screenshots: [],
  currentPath: null,
};

export function exploreReducer(
  state: ExploreMachineState,
  action: ExploreAction
): ExploreMachineState {
  switch (action.type) {
    case "START":
      return {
        ...initialExploreState,
        url: action.url,
        intent: action.intent,
        state: "connecting",
      };

    case "TRANSITION":
      return {
        ...state,
        state: action.state,
      };

    case "ADD_ACTIVITY": {
      const exists = state.activities.find((a) => a.id === action.activity.id);
      const activities = exists
        ? state.activities.map((a) =>
            a.id === action.activity.id ? action.activity : a
          )
        : [...state.activities, action.activity];
      return {
        ...state,
        activities,
      };
    }

    case "SET_AUTH_REQUIRED":
      return {
        ...state,
        state: "auth_required",
        credentialRequest: action.request,
        authMode: "choice",
      };

    case "SET_AUTH_MODE":
      return {
        ...state,
        authMode: action.mode,
      };

    case "SET_QUESTION":
      return {
        ...state,
        state: "asking",
        question: action.question,
      };

    case "SET_DISCOVERIES":
      return {
        ...state,
        discoveries: action.discoveries,
      };

    case "SET_MISSIONS": {
      const recommendedIds = action.missions
        .filter((m) => m.recommended)
        .map((m) => m.id);
      const defaultSelected =
        recommendedIds.length > 0
          ? recommendedIds
          : action.missions.slice(0, 1).map((m) => m.id);

      return {
        ...state,
        missions: action.missions,
        recommendationNote: action.recommendation,
        selectedMissionIds: defaultSelected,
      };
    }

    case "TOGGLE_MISSION": {
      const isSelected = state.selectedMissionIds.includes(action.id);
      const nextSelected = isSelected
        ? state.selectedMissionIds.filter((id) => id !== action.id)
        : [...state.selectedMissionIds, action.id];
      return {
        ...state,
        selectedMissionIds: nextSelected,
      };
    }

    case "SELECT_ALL_MISSIONS": {
      const allSelected = state.selectedMissionIds.length === state.missions.length;
      return {
        ...state,
        selectedMissionIds: allSelected ? [] : state.missions.map((m) => m.id),
      };
    }

    case "UPDATE_MISSION": {
      return {
        ...state,
        missions: state.missions.map((m) =>
          m.id === action.mission.id ? action.mission : m
        ),
      };
    }

    case "MISSION_CREATED":
      return {
        ...state,
        state: "mission_created",
        createdProjectId: action.projectId,
      };

    case "ADD_SCREENSHOT": {
      const entry: ScreenshotEntry = {
        id: `ss-${++_screenshotCounter}`,
        url: action.screenshot,
        timestamp: Date.now(),
        label: action.label,
      };
      return {
        ...state,
        screenshots: [...state.screenshots, entry],
        currentPath: state.currentPath,
      };
    }

    case "SET_PAGE":
      return {
        ...state,
        currentPath: action.path || state.currentPath,
      };

    case "FAIL":
      return {
        ...state,
        state: "failed",
        error: action.error,
      };

    case "CANCEL":
      return {
        ...state,
        state: "cancelled",
      };

    case "RESET":
      return {
        ...initialExploreState,
      };

    default:
      return state;
  }
}

export function useExploreMachine(initialUrl?: string, initialIntent?: string) {
  const [state, dispatch] = useReducer(exploreReducer, {
    ...initialExploreState,
    url: initialUrl || "",
    intent: initialIntent,
    state: initialUrl ? "connecting" : "idle",
  });

  const start = useCallback((url: string, intent?: string) => {
    dispatch({ type: "START", url, intent });
  }, []);

  const transition = useCallback((targetState: ExploreState) => {
    dispatch({ type: "TRANSITION", state: targetState });
  }, []);

  const addActivity = useCallback((activity: AgentActivityItem) => {
    dispatch({ type: "ADD_ACTIVITY", activity });
  }, []);

  const setAuthRequired = useCallback((request: CredentialRequest) => {
    dispatch({ type: "SET_AUTH_REQUIRED", request });
  }, []);

  const setAuthMode = useCallback((mode: AuthMode) => {
    dispatch({ type: "SET_AUTH_MODE", mode });
  }, []);

  const setQuestion = useCallback((question: AgentQuestionItem) => {
    dispatch({ type: "SET_QUESTION", question });
  }, []);

  const setDiscoveries = useCallback((discoveries: DiscoveryItem[]) => {
    dispatch({ type: "SET_DISCOVERIES", discoveries });
  }, []);

  const setMissions = useCallback(
    (missions: SuggestedMission[], recommendation?: string) => {
      dispatch({ type: "SET_MISSIONS", missions, recommendation });
    },
    []
  );

  const toggleMission = useCallback((id: string) => {
    dispatch({ type: "TOGGLE_MISSION", id });
  }, []);

  const selectAllMissions = useCallback(() => {
    dispatch({ type: "SELECT_ALL_MISSIONS" });
  }, []);

  const updateMission = useCallback((mission: SuggestedMission) => {
    dispatch({ type: "UPDATE_MISSION", mission });
  }, []);

  const setMissionCreated = useCallback((projectId: string) => {
    dispatch({ type: "MISSION_CREATED", projectId });
  }, []);

  const fail = useCallback((error: string) => {
    dispatch({ type: "FAIL", error });
  }, []);

  const cancel = useCallback(() => {
    dispatch({ type: "CANCEL" });
  }, []);

  const addScreenshot = useCallback((screenshot: string, label?: string) => {
    dispatch({ type: "ADD_SCREENSHOT", screenshot, label });
  }, []);

  const setPage = useCallback((url: string, title?: string, path?: string, screenshot?: string) => {
    dispatch({ type: "SET_PAGE", url, title, path, screenshot });
  }, []);

  const reset = useCallback(() => {
    dispatch({ type: "RESET" });
  }, []);

  return {
    state,
    dispatch,
    start,
    transition,
    addActivity,
    setAuthRequired,
    setAuthMode,
    setQuestion,
    setDiscoveries,
    setMissions,
    toggleMission,
    selectAllMissions,
    updateMission,
    setMissionCreated,
    addScreenshot,
    setPage,
    fail,
    cancel,
    reset,
  };
}
