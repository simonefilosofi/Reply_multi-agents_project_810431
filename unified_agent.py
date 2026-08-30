import os
import traceback
import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from e2b_code_interpreter import Sandbox

from utils.llm import structured_model

load_dotenv()

class CodeOutput(BaseModel):
    code: str = Field(description="Python code defining a function called 'clean_data(df)'.")

def run_mechanic_in_cloud(dataset: dict, approved_errors: str):
    print("Running Code Generator...")
    structured_llm = structured_model(CodeOutput)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a Python data engineer. Write a function `clean_data(df)` that fixes ONLY the approved errors.
        
        CRITICAL RULES & PANDAS CHEAT SHEET:
        1. NEVER drop rows.
        2. Relational Imputation: NEVER fill missing or bad values with the global mode. If fixing a mapping contradiction, you MUST calculate the correct value based on the specific category using `groupby().transform()`.
        3. Format Corrections: Strip rogue letters using str.replace or regex, then cast to numeric.
        4. NO INPLACE: NEVER use `inplace=True`.
        
        Assume `import pandas as pd` and `import numpy as np` are executed. Do not use markdown formatting."""),
        ("user", "Dataset Schema & Data: {dataset}\n\nAPPROVED ERRORS TO FIX:\n{errors}\n\nWrite the code.")
    ])
    
    result = (prompt | structured_llm).invoke({
        "dataset": dataset,
        "errors": approved_errors
    })
    
    print("\n--- GENERATED CODE ---\n")
    print(result.code)
    print("\n----------------------\n")
    
    print("Sending code to E2B Cloud Sandbox...")
    try:
        with Sandbox.create() as sandbox:
            setup_code = f"""
import pandas as pd
import numpy as np
dataset = {dataset}
df = pd.DataFrame(dataset)
"""
            sandbox.run_code(setup_code)
            
            exec_result = sandbox.run_code(result.code)
            
            if getattr(exec_result, 'error', None):
                print(f"Sandbox Function Definition Failed:\n{exec_result.error}")
                return
            
            run_code = """
cleaned_df = clean_data(df)
print(cleaned_df.to_string())
"""
            run_result = sandbox.run_code(run_code)
            
            if getattr(run_result, 'error', None):
                print(f"Sandbox Execution Failed:\n{run_result.error}")
            else:
                print("CLOUD EXECUTION SUCCESS\n")
                print("Cleaned DataFrame from E2B:")
                output = getattr(run_result, 'text', '')
                if not output and hasattr(run_result, 'logs'):
                    output = "".join(getattr(run_result.logs, 'stdout', []))
                print(output)
                
    except Exception as e:
        print("E2B Connection Failed\n")
        print(traceback.format_exc())

if __name__ == "__main__":
    test_data = {
        "ente_code": [15, 22, 99, "88-B", 15],
        "municipality": ["Rome", "Milan", "Rome", "Naples", "Rome"],
        "employee_age": [40, 35, 25, 45, 12],
        "years_of_experience": [10, 5, 2, 20, 2]
    }
    
    simulated_approval = """
    1. Row index 2: The 'ente_code' for 'Rome' is 99, but functional dependency suggests it should be 15.
    2. Row index 3: The 'ente_code' '88-B' contains anomalous string formatting.
    """
    
    run_mechanic_in_cloud(test_data, simulated_approval)