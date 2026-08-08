from typing import Callable, Dict, List, Any, Optional
from pydantic import BaseModel, Field
import inspect
import json

class ToolParameter(BaseModel):
    """Definition of a tool parameter."""
    type: str
    description: str
    required: bool = True
    enum: Optional[List[str]] = None

class ToolDefinition(BaseModel):
    """Schema definition for a tool."""
    name: str
    description: str
    parameters: Dict[str, ToolParameter]

class AgentTool:
    """Base class for all agent tools."""
    
    def __init__(self, name: str, description: str, func: Callable):
        self.name = name
        self.description = description
        self.func = func
        self.schema = self._generate_schema()
        
    def _generate_schema(self) -> ToolDefinition:
        """Generate JSON schema from function signature."""
        sig = inspect.signature(self.func)
        params = {}
        
        for name, param in sig.parameters.items():
            if name == "self":
                continue
                
            # Default to string if no annotation
            param_type = "string"
            if param.annotation != inspect.Parameter.empty:
                if param.annotation == int:
                    param_type = "integer"
                elif param.annotation == float:
                    param_type = "number"
                elif param.annotation == bool:
                    param_type = "boolean"
                elif param.annotation == list:
                    param_type = "array"
                elif param.annotation == dict:
                    param_type = "object"
            
            # Extract description from docstring (simplified)
            # In a real system, we'd parse docstrings more robustly
            description = f"Parameter {name}"
            
            params[name] = ToolParameter(
                type=param_type,
                description=description,
                required=param.default == inspect.Parameter.empty
            )
            
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=params
        )
        
    def execute(self, **kwargs) -> Any:
        """Execute the tool with provided arguments."""
        return self.func(**kwargs)
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert to OpenAI-compatible tool definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        k: {"type": p.type, "description": p.description} 
                        for k, p in self.schema.parameters.items()
                    },
                    "required": [
                        k for k, p in self.schema.parameters.items() if p.required
                    ]
                }
            }
        }

class ToolRegistry:
    """Registry for managing available tools."""
    
    def __init__(self):
        self._tools: Dict[str, AgentTool] = {}
        
    def register(self, tool: AgentTool):
        """Register a new tool."""
        self._tools[tool.name] = tool
        
    def get_tool(self, name: str) -> Optional[AgentTool]:
        """Get a tool by name."""
        return self._tools.get(name)
        
    def list_tools(self) -> List[Dict[str, Any]]:
        """List all tool definitions."""
        return [tool.to_dict() for tool in self._tools.values()]
        
    def execute(self, name: str, args: Dict[str, Any]) -> Any:
        """Execute a tool by name with arguments."""
        tool = self.get_tool(name)
        if not tool:
            raise ValueError(f"Tool {name} not found")
            
        try:
            return tool.execute(**args)
        except Exception as e:
            return f"Error executing tool {name}: {str(e)}"

# Global registry instance
registry = ToolRegistry()
