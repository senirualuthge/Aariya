import { clamp } from '../utils/clamp';

export function applyActionsToState(state, actions) {
  const newState = { ...state };

  if (!state.intent) newState.intent = "NORMAL";
  
  if (!state.empathy) newState.empathy = 0.5;
  if (!state.assertiveness) newState.assertiveness = 0.5;

  actions.forEach(action => {
    switch (action.type) {
      case "REDUCE_ASSERTIVENESS":
        newState.assertiveness -= action.value;
        break;

      case "INCREASE_EMPATHY":
        newState.empathy += action.value;
        break;

      case "SWITCH_TO_COMFORT_MODE":
        newState.intent = "COMFORT";
        break;

      case "ENABLE_CLARIFICATION_MODE":
        newState.intent = "CLARIFY";
        break;

      case "MAXIMIZE_SAFETY_RESPONSE":
        newState.intent = "SAFE";
        newState.empathy = 1.0;
        break;
        
      case "OVERRIDE_MODE":
        newState.intent = action.value; // For the manual control panel
        break;
        
      default:
        break;
    }
  });

  // Clamp continuous values
  newState.assertiveness = clamp(newState.assertiveness, 0, 1);
  newState.empathy = clamp(newState.empathy, 0, 1);

  return newState;
}
