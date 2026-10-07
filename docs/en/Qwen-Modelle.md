# Qwen Models in Open WebUI

Apps → Open WebUI → **Qwen Models** opens `/apps/open_webui/models`.
The interface manages the local Ollama service (`127.0.0.1:11434`).
Open WebUI must use the same Ollama instance. Existing connection settings are not changed.

- Model families are loaded live from the official Ollama search, with variants including sizes and checksums taken from their tag pages. Catalog errors are displayed visibly.
- Installed models are read via `/api/tags`. The published checksum distinguishes current installations and updates of the same tag. Other sizes/generations remain separate models.
- Default view uses simple tags; all quantizations optional. Cloud/MLX variants are excluded. Downloads are pre-validated by a registry manifest with local model weights.
- Downloading and installing is explicitly performed via POST with CSRF protection. GET requests install nothing.
- A serial systemd worker utilizes Ollama's `/api/pull`, showing streaming progress, final local model verification, and clear error reporting. It survives server manager reboots. Runtime limit: 24 hours; read timeout without progress data: 180 seconds.
- Jobs reside privately in `/var/lib/server-manager/qwen-models`; orphaned jobs are detected as interrupted. Reinstalling can reuse existing download parts.
- A sleep blocker remains active during downloads. There is no automatic deletion of old models and no automatic selection of a model for chats.
- Sizes refer to downloads, not guaranteed RAM/VRAM requirements or runtime compatibility. Ollama reports insufficient memory or unsupported models as errors.

Sources: https://ollama.com/search?q=qwen and https://docs.ollama.com/api/pull

## Uninstallation

Installed Qwen models have a **Uninstall** button. The confirmation page displays the exact model name and requires explicit confirmation. Removal is performed via CSRF-protected POST to Ollama's DELETE /api/delete endpoint. During a model download, removal is blocked; a changed model checksum requires new confirmation. After removal, the local model list is checked. Chats and other model names are preserved; shared model data may limit the actually released storage.
