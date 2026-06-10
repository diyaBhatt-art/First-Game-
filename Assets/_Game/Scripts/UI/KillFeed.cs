using System.Collections.Generic;
using UnityEngine;
using TMPro;
using MMystery.Networking;
using MMystery.Core;

namespace MMystery.UI
{
    public class KillFeed : MonoBehaviour
    {
        [Header("Row Prefab & Container")]
        [SerializeField] private TMP_Text rowPrefab;
        [SerializeField] private RectTransform container;

        [Header("Stacking Layout")]
        [SerializeField] private float yStart = 200f; // top-right anchor starting Y
        [SerializeField] private float ySpacing = 35f; // spacing downward
        [SerializeField] private float xAnchor = -20f; // right side indent

        private const int POOL_SIZE = 6;
        private List<TMP_Text> pool = new List<TMP_Text>();
        private List<KillRowState> activeRows = new List<KillRowState>();

        private struct KillRowState
        {
            public TMP_Text textComponent;
            public float timeRemaining;
            public Color baseColor;
        }

        private void Awake()
        {
            if (container == null)
            {
                container = GetComponent<RectTransform>();
            }

            // Pre-instantiate pool rows
            if (rowPrefab != null)
            {
                for (int i = 0; i < POOL_SIZE; i++)
                {
                    TMP_Text row = Instantiate(rowPrefab, container);
                    row.gameObject.SetActive(false);
                    pool.Add(row);
                }
            }
        }

        private void OnEnable()
        {
            // Subscribe to authoritative multiplayer notifications
            GameManager.OnKillConfirmed += AddKillFeedEntry;
            
            // Subscribe to local singleplayer bullet hit notifications
            BulletController.OnKill += AddKillFeedEntryLocal;
        }

        private void OnDisable()
        {
            GameManager.OnKillConfirmed -= AddKillFeedEntry;
            BulletController.OnKill -= AddKillFeedEntryLocal;
        }

        private void AddKillFeedEntryLocal(string victim, string weapon)
        {
            // Shorthand for local tests: killer defaults to Murderer/Sheriff
            string killer = (weapon == "knife") ? "Murderer" : "Sheriff";
            AddKillFeedEntry(killer, victim, weapon);
        }

        public void AddKillFeedEntry(string killer, string victim, string weapon)
        {
            // Find next available deactivated row in pool
            TMP_Text rowText = null;
            foreach (var r in pool)
            {
                if (!r.gameObject.SetActive(false)) // if inactive
                {
                    rowText = r;
                    break;
                }
            }

            // Fallback: If pool is completely filled, steal the oldest active row
            if (rowText == null && activeRows.Count > 0)
            {
                var oldest = activeRows[0];
                activeRows.RemoveAt(0);
                rowText = oldest.textComponent;
            }

            if (rowText == null) return;

            // Format weapons icons
            string icon = (weapon == "knife") ? "⚔" : "🔫";
            rowText.text = $"{killer}  <color=#FF3B30>{icon}</color>  {victim}";

            // Reset layout and visual parameters
            rowText.gameObject.SetActive(true);
            Color alertRed = new Color(1f, 0.314f, 0.314f, 1f); // #FF5050 alpha=1

            KillRowState newState = new KillRowState
            {
                textComponent = rowText,
                timeRemaining = 4f, // 4 seconds lifespan
                baseColor = alertRed
            };

            activeRows.Add(newState);

            // Re-arrange active rows in stack positions
            RepositionActiveRows();
        }

        private void Update()
        {
            // Ticking lifespan down and fading alpha
            for (int i = activeRows.Count - 1; i >= 0; i--)
            {
                KillRowState state = activeRows[i];
                state.timeRemaining -= Time.deltaTime;

                if (state.timeRemaining <= 0f)
                {
                    // Fade complete: deactivate and return to pool
                    state.textComponent.gameObject.SetActive(false);
                    activeRows.RemoveAt(i);
                    RepositionActiveRows();
                }
                else
                {
                    // Apply linear alpha fade over remaining lifetime
                    float alpha = Mathf.Clamp01(state.timeRemaining / 4f);
                    Color col = state.baseColor;
                    col.a = alpha;
                    state.textComponent.color = col;
                    
                    // Write back struct modifications
                    activeRows[i] = state;
                }
            }
        }

        private void RepositionActiveRows()
        {
            // Positions stack from top-right downwards
            for (int index = 0; index < activeRows.Count; index++)
            {
                RectTransform rt = activeRows[index].textComponent.GetComponent<RectTransform>();
                if (rt != null)
                {
                    // Center pivot right-aligned anchors setup
                    rt.anchorMin = new Vector2(1f, 1f);
                    rt.anchorMax = new Vector2(1f, 1f);
                    rt.pivot = new Vector2(1f, 1f);

                    float yPos = yStart - (index * ySpacing);
                    rt.anchoredPosition = new Vector2(xAnchor, yPos);
                }
            }
        }
    }
}
