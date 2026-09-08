from __future__ import annotations

from agentes.config import load_yaml


def get_cv_config(cv_id: str) -> dict:
    data = load_yaml("config/cvs.yaml")

    for cv in data.get("cvs", []):
        if cv.get("id") == cv_id:
            return cv

    available = [
        cv.get("id")
        for cv in data.get("cvs", [])
    ]

    raise RuntimeError(
        f"CV ID {cv_id!r} no existe. "
        f"Disponibles: {available}"
    )


async def get_available_resumes(page) -> list[dict]:
    select = page.locator(
        "#job_application_resume_id"
    )

    if await select.count() == 0:
        raise RuntimeError(
            "No encontré #job_application_resume_id"
        )

    return await select.evaluate(
        """
        el => Array.from(el.options)
            .filter(o => o.value)
            .map(o => ({
                value: o.value,
                filename: (o.textContent || '').trim(),
                selected: o.selected
            }))
        """
    )


async def get_selected_resume(page) -> dict | None:
    select = page.locator(
        "#job_application_resume_id"
    )

    if await select.count() == 0:
        return None

    return await select.evaluate(
        """
        el => {
            const option = el.options[el.selectedIndex];

            if (!option || !option.value) {
                return null;
            }

            return {
                value: option.value,
                filename: (
                    option.textContent || ''
                ).trim()
            };
        }
        """
    )


async def select_cv(
    page,
    cv_id: str,
) -> dict:

    cv = get_cv_config(cv_id)

    target_filename = cv["filename"]

    select = page.locator(
        "#job_application_resume_id"
    )

    if await select.count() == 0:
        raise RuntimeError(
            "Get on Board no muestra selector de CV."
        )

    result = await select.evaluate(
        """
        (el, filename) => {

            const options = Array.from(
                el.options
            );

            const target = options.find(
                o => (
                    o.textContent || ''
                ).trim() === filename
            );

            if (!target) {
                return {
                    ok: false,
                    available: options
                        .filter(o => o.value)
                        .map(o => (
                            o.textContent || ''
                        ).trim())
                };
            }

            el.value = target.value;

            for (const option of options) {
                option.selected =
                    option.value === target.value;
            }

            // Rails / Stimulus / Chosen
            el.dispatchEvent(
                new Event(
                    'input',
                    { bubbles: true }
                )
            );

            el.dispatchEvent(
                new Event(
                    'change',
                    { bubbles: true }
                )
            );

            // Chosen normalmente usa jQuery.
            if (
                window.jQuery &&
                window.jQuery(el).trigger
            ) {
                window.jQuery(el).trigger(
                    'chosen:updated'
                );
            }

            return {
                ok: true,
                value: target.value,
                filename: (
                    target.textContent || ''
                ).trim()
            };
        }
        """,
        target_filename,
    )

    if not result.get("ok"):
        raise RuntimeError(
            "El CV recomendado no está almacenado "
            "en Get on Board.\n"
            f"Buscado: {target_filename}\n"
            f"Disponibles: {result.get('available')}"
        )

    # --------------------------------------------------------
    # GUARDRAIL: verificar el SELECT REAL
    # --------------------------------------------------------

    selected = await get_selected_resume(
        page
    )

    if not selected:
        raise RuntimeError(
            "No quedó ningún CV seleccionado."
        )

    if (
        selected["filename"]
        != target_filename
    ):
        raise RuntimeError(
            "CV GUARDRAIL FAILED: "
            f"esperado={target_filename}, "
            f"actual={selected['filename']}"
        )

    # --------------------------------------------------------
    # Verificar también la UI de Chosen si está presente.
    # --------------------------------------------------------

    chosen_text = ""

    chosen = page.locator(
        "#job_application_resume_id_chosen "
        ".chosen-single span"
    )

    if await chosen.count():
        chosen_text = (
            await chosen.inner_text()
        ).strip()

    return {
        "cv_id": cv_id,
        "filename": target_filename,
        "resume_id": selected["value"],
        "ui_filename": chosen_text,
    }


async def assert_cv_selected(
    page,
    cv_id: str,
) -> dict:

    cv = get_cv_config(cv_id)

    selected = await get_selected_resume(
        page
    )

    if not selected:
        raise RuntimeError(
            "CV GUARDRAIL: "
            "no hay CV seleccionado."
        )

    if (
        selected["filename"]
        != cv["filename"]
    ):
        raise RuntimeError(
            "\n🛑 CV GUARDRAIL\n"
            f"Agente pidió: {cv['filename']}\n"
            f"Formulario tiene: "
            f"{selected['filename']}\n"
            "POSTULACIÓN BLOQUEADA."
        )

    return selected
