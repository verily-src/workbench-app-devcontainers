"""
CLI entry point for verily-chat.

Usage:
    verily-chat ask "question" --table <fq_table> --bucket <bucket> --model <model>
    verily-chat session --project <project> --bucket <bucket> --model <model>
"""

from __future__ import annotations

import sys

import click


@click.group()
@click.version_option(package_name="verily-chat")
def main():
    """Chat over BigQuery metadata: Q&A from profiling output."""


@main.command()
@click.argument("question")
@click.option("--table", default=None, help="Fully-qualified table name (project.dataset.table)")
@click.option("--project", default=None, help="GCP project containing the data")
@click.option("--bucket", required=True, help="GCS bucket with profiling output")
@click.option("--model", default="gemini-3-flash-preview", help="Gemini model name")
@click.option("--billing-project", default=None, help="Project for Vertex AI billing")
def ask(question: str, table: str | None, project: str | None, bucket: str, model: str, billing_project: str | None):
    """Ask a single question about table metadata."""
    from verily_chat.models import ChatContext
    from verily_chat.chat import chat as do_chat

    ctx = _build_context(table=table, project=project, bucket=bucket, billing_project=billing_project)
    bp = billing_project or ctx.project_id

    reply = do_chat(question, ctx, model=model, project_id=bp)
    click.echo(reply.content)
    if reply.sql:
        click.echo(f"\nExtracted SQL:\n{reply.sql}")


@main.command()
@click.option("--project", required=True, help="GCP project containing the data")
@click.option("--bucket", required=True, help="GCS bucket with profiling output")
@click.option("--model", default="gemini-3-flash-preview", help="Gemini model name")
@click.option("--billing-project", default=None, help="Project for Vertex AI billing")
@click.option("--table", default=None, help="Focus on a specific table")
def session(project: str, bucket: str, model: str, billing_project: str | None, table: str | None):
    """Interactive multi-turn chat session."""
    from verily_chat.models import ChatContext, ChatMessage
    from verily_chat.chat import chat as do_chat

    ctx = _build_context(table=table, project=project, bucket=bucket, billing_project=billing_project)
    bp = billing_project or ctx.project_id

    history: list[ChatMessage] = []
    click.echo("verily-chat session (type 'quit' to exit, 'clear' to reset)")
    click.echo(f"Project: {ctx.project_id} | Tables with profiles: {len(ctx.tech_profiles) + len(ctx.sem_profiles)}")
    if ctx.fq_table:
        click.echo(f"Focused on: {ctx.fq_table}")
    click.echo()

    while True:
        try:
            user_input = click.prompt("You", prompt_suffix="> ")
        except (EOFError, KeyboardInterrupt):
            click.echo("\nBye!")
            break

        if user_input.strip().lower() == "quit":
            break
        if user_input.strip().lower() == "clear":
            history.clear()
            click.echo("(conversation cleared)")
            continue
        if not user_input.strip():
            continue

        history.append(ChatMessage(role="user", content=user_input))
        reply = do_chat(user_input, ctx, history=history[:-1], model=model, project_id=bp)
        history.append(reply)

        click.echo(f"\nAssistant: {reply.content}")
        if reply.sql:
            click.echo(f"\nSQL:\n{reply.sql}")
        click.echo()


def _build_context(
    table: str | None,
    project: str | None,
    bucket: str,
    billing_project: str | None,
) -> "ChatContext":
    """Load profiles from GCS and build a ChatContext."""
    from verily_profiler.storage import parse_fq_table, read_json_if_exists, scan_profile_availability
    from verily_chat.models import ChatContext

    bp = billing_project
    data_project = project

    if table and not data_project:
        parts = table.split(".")
        if len(parts) == 3:
            data_project = parts[0]

    if not data_project:
        click.echo("Could not determine project. Use --project or provide a fully-qualified --table.", err=True)
        sys.exit(1)

    bp = bp or data_project

    tech_profiles: dict = {}
    sem_profiles: dict = {}

    if table:
        from verily_profiler import read_tech_profile, read_sem_profile

        tech = read_tech_profile(bucket, table, project_id=bp)
        if tech:
            tech_profiles[table] = tech
        sem = read_sem_profile(bucket, table, project_id=bp)
        if sem:
            sem_profiles[table] = sem
    else:
        avail = scan_profile_availability(bucket, data_project, billing_project_id=bp)
        for fq, info in avail.items():
            if info.get("technical"):
                from verily_profiler import read_tech_profile
                t = read_tech_profile(bucket, fq, project_id=bp)
                if t:
                    tech_profiles[fq] = t
            if info.get("semantic"):
                from verily_profiler import read_sem_profile
                s = read_sem_profile(bucket, fq, project_id=bp)
                if s:
                    sem_profiles[fq] = s

    return ChatContext(
        project_id=data_project,
        billing_project=bp,
        fq_table=table,
        tech_profiles=tech_profiles,
        sem_profiles=sem_profiles,
    )


if __name__ == "__main__":
    main()
