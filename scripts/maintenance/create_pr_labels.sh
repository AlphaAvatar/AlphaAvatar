create_or_update_label() {
  name="$1"
  color="$2"
  desc="$3"

  if gh label list --limit 200 | awk -F'\t' '{print $1}' | grep -Fxq "$name"; then
    gh label edit "$name" --color "$color" --description "$desc"
  else
    gh label create "$name" --color "$color" --description "$desc"
  fi
}

create_or_update_label feature 1D76DB "New features"
create_or_update_label enhancement A2EEEF "Enhancements"
create_or_update_label bug D73A4A "Bug fixes"
create_or_update_label docs 0075CA "Documentation updates"
create_or_update_label documentation 0075CA "Documentation updates"
create_or_update_label persona 8A2BE2 "Persona plugin changes"
create_or_update_label memory 5319E7 "Memory plugin changes"
create_or_update_label chore C5DEF5 "Maintenance changes"
create_or_update_label dependencies 0366D6 "Dependency updates"
create_or_update_label refactor C5DEF5 "Code refactoring"
create_or_update_label ignore-for-release BFDADC "Exclude from release notes"
