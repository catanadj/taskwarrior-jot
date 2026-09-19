"""Composition for task and project browsing workspaces."""

from __future__ import annotations


def compose_browse_pane():
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Button, Checkbox, DataTable, Input, Static, TabbedContent, TabPane

    with Horizontal(id="browse-top"):
        with TabbedContent(initial="task-browser-pane", id="browse-browser-tabs"):
            with TabPane("Tasks", id="task-browser-pane"):
                with Horizontal():
                    with Vertical(id="browse-tasks"):
                        yield Static("Tasks", classes="title")
                        with Horizontal(id="task-filter-bar"):
                            yield Input(placeholder="Project filter", id="task-filter-project")
                            yield Input(placeholder="Tag filter", id="task-filter-tag")
                            yield Checkbox("Notes only", id="task-filter-notes")
                            yield Button("Clear", id="task-filter-clear")
                        tasks = DataTable(id="tasks-table", cursor_type="row")
                        tasks.add_columns("id", "description", "project", "progress", "tags", "notes")
                        yield tasks
                    with Vertical(id="task-workspace"):
                        yield Static("Task Workspace", classes="title")
                        with TabbedContent(initial="task-summary-pane", id="task-workspace-tabs"):
                            with TabPane("Summary", id="task-summary-pane"):
                                yield Static("Select a task row to load details.", id="task-summary")
                            with TabPane("Task Note", id="task-note-pane"):
                                yield Static("No task note loaded.", id="task-note-preview")
                            with TabPane("Chain Note", id="chain-note-pane"):
                                yield Static("No chain note loaded.", id="chain-note-preview")
                            with TabPane("Project Note", id="project-note-pane"):
                                yield Static("No project note loaded.", id="project-note-preview")
                            with TabPane("Events", id="task-events-pane"):
                                yield Static("No events loaded.", id="task-events-preview")
                            with TabPane("Resources", id="task-resources-pane"):
                                yield Static("No resources loaded.", id="task-resources-preview")
                            with TabPane("Progress", id="task-progress-pane"):
                                yield Static("No progress loaded.", id="task-progress-preview")
            with TabPane("Projects", id="project-browser-pane"):
                with Horizontal():
                    with Vertical(id="browse-projects"):
                        projects = DataTable(id="projects-table", cursor_type="row")
                        projects.add_columns("project tree", "tasks", "progress", "note", "updated")
                        yield Static("Projects", classes="title")
                        yield projects
                    with Vertical(id="project-workspace"):
                        yield Static("Project Workspace", classes="title")
                        with TabbedContent(initial="project-summary-pane", id="project-workspace-tabs"):
                            with TabPane("Summary", id="project-summary-pane"):
                                yield Static("Select a project row to load details.", id="project-summary")
                            with TabPane("Project Note", id="project-note-body-pane"):
                                yield Static("No project note loaded.", id="project-note-body")
                            with TabPane("Resources", id="project-resources-pane"):
                                yield Static("No resources loaded.", id="project-resources-preview")
                            with TabPane("Progress", id="project-progress-pane"):
                                yield Static("No progress loaded.", id="project-progress-preview")
