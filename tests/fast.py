# app.py
from fastapi import FastAPI, status
from pydantic import BaseModel
import uvicorn
import asyncio
from typing import Dict, Any
from src.omnidaemon.sdk import OmniDaemonSDK

app = FastAPI(title="AI Document Processing Platform")
sdk = OmniDaemonSDK()


# ----------------------------------------
# Schemas
# ----------------------------------------
class TaskResponse(BaseModel):
    status: str
    topic: str
    message: str


class RequestData(BaseModel):
    payload: Dict[str, Any]


# ----------------------------------------
# Callback Webhooks — Agents send results here
# ----------------------------------------
@app.post("/document_conversion_result", status_code=status.HTTP_200_OK)
async def document_conversion_callback(data: RequestData):
    new_data = data.payload
    print(f"📄 Document Conversion Agent Result: {new_data}")
    return {"status": "success"}


@app.post("/data_extraction_result", status_code=status.HTTP_200_OK)
async def data_extraction_callback(data: RequestData):
    new_data = data.payload
    print(f"🔍 Data Extraction Agent Result: {new_data}")
    return {"status": "success"}


@app.post("/quality_assurance_result", status_code=status.HTTP_200_OK)
async def quality_assurance_callback(data: RequestData):
    new_data = data.payload
    print(f"✅ Quality Assurance Agent Result: {new_data}")
    return {"status": "success"}


# ----------------------------------------
# User-Facing Task Triggers
# ----------------------------------------
@app.post(
    "/convert_document",
    response_model=TaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def convert_document(source_format: str, target_format: str, document_path: str):
    """
    Trigger a document conversion agent for automated format conversion and standardization.
    """
    payload = {
        "source_format": source_format,
        "target_format": target_format,
        "document_path": document_path,
        "content": """convert to capital letter and save it as md file named is convert.md: today i want to take a quiet walk around the park, maybe sit under a tree and think about some new ideas for my next project.""",
        "webhook": "http://localhost:8000/document_conversion_result",
    }
    await sdk.publish_task("document.conversion.tasks", payload)
    return TaskResponse(
        status="queued",
        topic="document.conversion.tasks",
        message=f"Converting document from {source_format} to {target_format}...",
    )


@app.post(
    "/extract_data", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED
)
async def extract_data(
    source_type: str, document_path: str, extraction_schema: Dict[str, Any]
):
    """
    Trigger a data extraction agent for structured data extraction from unstructured sources.
    """
    payload = {
        "source_type": source_type,
        "document_path": document_path,
        "extraction_schema": extraction_schema,
        "content": "convert this document to pdf",
        "webhook": "http://localhost:8000/data_extraction_result",
    }
    await sdk.publish_task("data.extraction.tasks", payload)
    return TaskResponse(
        status="queued",
        topic="data.extraction.tasks",
        message=f"Extracting data from {source_type} document...",
    )


@app.post(
    "/validate_quality",
    response_model=TaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def validate_quality(document_id: str, compliance_rules: Dict[str, Any]):
    """
    Trigger a quality assurance agent for automated compliance and accuracy checking.
    """
    payload = {
        "document_id": document_id,
        "compliance_rules": compliance_rules,
        "webhook": "http://localhost:8000/quality_assurance_result",
    }
    await sdk.publish_task("quality.assurance.tasks", payload)
    return TaskResponse(
        status="queued",
        topic="quality.assurance.tasks",
        message=f"Validating quality and compliance for document {document_id}...",
    )


# ----------------------------------------
# Entry Point
# ----------------------------------------
if __name__ == "__main__":
    uvicorn.run("fast:app", host="0.0.0.0", port=8004, reload=True)
