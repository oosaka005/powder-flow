import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "web_ui_gateway.app:app",
        host=os.getenv("POWDER_WEB_HOST", "0.0.0.0"),
        port=int(os.getenv("POWDER_WEB_PORT", "8000")),
    )
