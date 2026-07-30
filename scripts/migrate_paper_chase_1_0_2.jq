.[0] as $current
| .[1] as $reference
| $current
| .version = "1.0.2"
| .initial_scene_id = "client_briefing"
| .scenes = [
    $current.scenes[] as $scene
    | first($reference.scenes[] | select(.id == $scene.id)) as $safe
    | $scene
      + {
          entity_ids: $safe.entity_ids,
          checkpoint_ids: [
            $safe.checkpoint_ids[]
            | if . == "follow_graveyard_tracks" then "inspect_grave_area" else . end
          ],
          exits: $safe.exits,
          available_exits: ($safe.available_exits // []),
          narrative_details: ($scene.narrative_details // [])
        }
  ]
| .entities = (
    [
      $current.entities[] as $entity
      | if $entity.id == "caretaker_bottle" then
          empty
        elif $entity.id == "douglas" then
          first($reference.entities[] | select(.id == "cemetery_figure")) as $safe
          | $entity * $safe
        else
          first($reference.entities[] | select(.id == $entity.id)) as $safe
          | $entity
            * {
                player_visible_name: ($safe.player_visible_name // $entity.name),
                player_visible_aliases: (
                  $safe.player_visible_aliases // $entity.aliases // []
                ),
                content: $safe.content,
                visibility: ($safe.visibility // $entity.visibility // {"audience": "all"}),
                narrative_details: ($safe.narrative_details // [])
              }
        end
      | .player_visible_name = (.player_visible_name // .name)
      | .player_visible_aliases = (.player_visible_aliases // .aliases // [])
      | .secrets = (if has("secrets") then .secrets else null end)
      | .information_item_ids = (.information_item_ids // [])
      | .narrative_details = (.narrative_details // [])
    ]
    + [
        first($reference.entities[] | select(.id == "surveillance_area"))
        | .player_visible_name = (.player_visible_name // .name)
        | .player_visible_aliases = (.player_visible_aliases // .aliases // [])
        | .secrets = (if has("secrets") then .secrets else null end)
        | .visibility = (.visibility // {"audience": "all"})
        | .information_item_ids = (.information_item_ids // [])
        | .narrative_details = (.narrative_details // [])
      ]
  )
| .entities = [
    .entities[]
    | if .id == "favorite_grave" then
        .visibility.discovery_rule = "entity.favorite_grave.state.identified == true"
      elif .id == "case_tracker" then
        .visibility = {"audience": "keeper"}
      else
        .
      end
  ]
| .checkpoints = [
    $reference.checkpoints[]
    | if .id == "follow_graveyard_tracks" then
        .id = "inspect_grave_area"
        | .visibility.discovery_rule = "entity.favorite_grave.state.identified == true"
      else
        .
      end
    | if .id == "intimidate_caretaker" or .id == "bribe_caretaker" then
        .outcomes.success.ops += [
          {
            "op": "set",
            "path": "entity.favorite_grave.state.identified",
            "value": true
          }
        ]
      else
        .
      end
  ]
| .module_rules = $reference.module_rules
| .win_conditions = $reference.win_conditions
| .information_items = [
    $current.information_items[]
    | .title = (
        .title
        // {
          "lyla_cemetery_sighting": "莱拉的回忆",
          "melodias_night_sighting": "看守的夜间目击",
          "cemetery_dance_report": "墓地旧闻",
          "hilda_ghoul_statement": "希尔达的陈述",
          "diary_tunnel_clue": "日记中的地下线索",
          "douglas_true_nature": "人影的真实身份",
          "douglas_confession": "道格拉斯的选择"
        }[.id]
      )
    | .summary = (.summary // .content)
  ]
