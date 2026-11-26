import pytest

from app.agent_tools import lint_prompt


def errors(text):
    return [issue for issue in lint_prompt(text, 'local-edit') if issue['severity'] == 'error']


@pytest.mark.parametrize('instruction', [
    'Do not recreate from scratch.',
    'Never completely redesign the artwork.',
    "Don't create an entirely new image.",
    'Avoid generating from scratch.',
    'Work without recreating from scratch.',
    'Recreating from scratch is prohibited.',
    'Do not replace the background. Preserve the background exactly.',
    'Change the sky. Preserve the background exactly.',
    'Correct the button within [0.2, 0.3, 0.4, 0.5].',
])
def test_local_edit_prohibitions_and_coordinates_are_not_conflicts(instruction):
    assert not errors('Edit only the height button. ' + instruction + '\nOutput: PNG.')


@pytest.mark.parametrize('instruction', [
    'Recreate the product from scratch.',
    'Create an entirely new artwork.',
    'Completely redesign the product.',
    'Do not change the button, but completely redesign the product.',
    'Do not change the button. Recreate from scratch.',
    'Do not change the button and create an entirely new artwork.',
    'Not only adjust the button but recreate from scratch.',
    'Replace the background. Preserve the background exactly.',
    'Change the sky. Do not change the sky.',
    'Use a new environment. Preserve the environment exactly.',
    'Correct [specific structural area] following [direction].',
])
def test_actual_redesign_conflicts_and_unfilled_placeholders_still_block(instruction):
    assert errors('Edit only the height button. ' + instruction + '\nOutput: PNG.')
