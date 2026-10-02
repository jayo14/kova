/**
 * Flow API compatibility module.
 * Re-exports mission APIs using backend flow terminology.
 */

export {
  getMissions as getFlows,
  getMission as getFlow,
  createMission as createFlow,
  updateMission as updateFlow,
  deleteMission as deleteFlow,
  getMissionExecutions as getFlowExecutions,
  runMission as runFlow,
} from "./missions";

export type {
  Mission as Flow,
  CreateMissionInput as CreateFlowInput,
  UpdateMissionInput as UpdateFlowInput,
  MissionExecution as FlowExecution,
} from "@/lib/types";
