using System;
using System.Collections;
using UnityEngine;
using UnityEngine.UI;
using TMPro;
using MMystery.Core;

namespace MMystery.UI
{
    public class RoleRevealScreen : MonoBehaviour
    {
        [Header("UI Visual Toggles")]
        [SerializeField] private GameObject overlayPanel;
        [SerializeField] private Image backgroundTint;
        [SerializeField] private TMP_Text roleTitleText;
        [SerializeField] private TMP_Text roleDescriptionText;
        [SerializeField] private Button readyButton;

        public event Action OnReady;

        private Coroutine dismissCoroutine;

        private void Start()
        {
            if (readyButton != null)
            {
                readyButton.onClick.AddListener(Dismiss);
            }

            // Hide on initial load
            if (overlayPanel != null)
            {
                overlayPanel.SetActive(false);
            }
        }

        public void ShowReveal(RoleDefinitionSO role)
        {
            if (role == null || overlayPanel == null) return;

            StopAllCoroutines();
            overlayPanel.SetActive(true);

            // 1. Assign role colors and title
            roleTitleText.text = role.displayName.ToUpper();
            roleTitleText.color = role.roleColor;

            // Soft color tint on dark background overlay
            if (backgroundTint != null)
            {
                Color tint = role.roleColor;
                tint.a = 0.15f; // Soft ambient alpha overlay
                backgroundTint.color = tint;
            }

            // 2. Set static role instructions descriptions
            if (role.roleId == "murderer")
            {
                roleDescriptionText.text = "You are the MURDERER\nKill everyone before time runs out.";
            }
            else if (role.roleId == "sheriff")
            {
                roleDescriptionText.text = "You are the SHERIFF\nYou have one bullet. Use it wisely.";
            }
            else
            {
                roleDescriptionText.text = "You are INNOCENT\nCollect M Bucks and survive 3 minutes.";
            }

            // 3. Start auto-dismiss timer of 3 seconds
            dismissCoroutine = StartCoroutine(AutoDismissCoroutine(3f));
        }

        private IEnumerator AutoDismissCoroutine(float delay)
        {
            yield return new WaitForSeconds(delay);
            Dismiss();
        }

        public void Dismiss()
        {
            StopAllCoroutines();
            if (overlayPanel != null && overlayPanel.activeSelf)
            {
                overlayPanel.SetActive(false);
                OnReady?.Invoke();
                Debug.Log("RoleRevealScreen: Overlay dismissed.");
            }
        }
    }
}
