"""Read what Discord renders without treating V2 message.content as visible UI."""

from tier_ui import visible_text


def call_text(call):
    return "\n".join(
        filter(
            None,
            (
                call.args[0] if call.args and isinstance(call.args[0], str) else "",
                call.kwargs.get("content") or "",
                visible_text(call.kwargs.get("view")),
                visible_text(call.kwargs.get("embed")),
                visible_text(call.kwargs.get("embeds")),
            ),
        )
    )
