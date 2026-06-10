using UnityEngine;
using TMPro;
using MMystery.Core;

namespace MMystery.Players
{
    public class AvatarController : MonoBehaviour
    {
        [Header("Animator & Mesh References")]
        [SerializeField] private Animator animator;
        [SerializeField] private SkinnedMeshRenderer bodyRenderer;

        [Header("Weapon GameObjects")]
        [SerializeField] private GameObject knifeVisual;
        [SerializeField] private GameObject gunVisual;

        [Header("Billboard Name Tag")]
        [SerializeField] private TMP_Text nameTagText;
        [SerializeField] private Vector3 nameTagOffset = new Vector3(0f, 2.2f, 0f);

        private PlayerController _playerController;
        private PlayerData data;

        private void Start()
        {
            _playerController = GetComponentInParent<PlayerController>();
            
            // Set up name tag positions
            if (nameTagText != null)
            {
                nameTagText.transform.localPosition = nameTagOffset;
                nameTagText.alignment = TextAlignmentOptions.Center;
            }
        }

        private void Update()
        {
            // Sync to local PlayerController data if not manually injected
            if (_playerController != null && _playerController.data != null)
            {
                SyncToData(_playerController.data);
            }
        }

        public void SyncToData(PlayerData d)
        {
            data = d;
            if (data == null) return;

            // 1. Update Billboard Text Name
            if (nameTagText != null)
            {
                nameTagText.text = data.DisplayName;
            }

            // 2. Drive Locomotion Animations
            if (animator != null)
            {
                float speed = 0f;
                if (data.IsMoving)
                {
                    speed = (data.Role != null && data.Role.roleId == "murderer") ? 1.0f : 0.5f;
                }
                
                animator.SetFloat("Speed", speed);
                animator.SetBool("IsAlive", data.IsAlive);
            }

            // 3. Toggles Weapon Meshes (active only when alive)
            if (knifeVisual != null)
            {
                knifeVisual.SetActive(data.Role != null && data.Role.hasKnife && data.IsAlive);
            }

            if (gunVisual != null)
            {
                gunVisual.SetActive(data.Role != null && data.Role.hasGun && data.IsAlive);
            }

            // 4. Update Facings
            if (data.FacingDirection.magnitude > 0.01f)
            {
                Vector3 lookTarget = new Vector3(data.FacingDirection.x, 0f, data.FacingDirection.y);
                transform.rotation = Quaternion.Slerp(transform.rotation, Quaternion.LookRotation(lookTarget), Time.deltaTime * 15f);
            }
        }

        public void TriggerAttack()
        {
            if (animator != null)
            {
                animator.SetTrigger("Attack");
            }
        }

        private void LateUpdate()
        {
            // Billboard rotation (name tag always faces Main Camera)
            if (nameTagText != null && Camera.main != null)
            {
                nameTagText.transform.rotation = Quaternion.LookRotation(nameTagText.transform.position - Camera.main.transform.position);
            }
        }
    }
}
