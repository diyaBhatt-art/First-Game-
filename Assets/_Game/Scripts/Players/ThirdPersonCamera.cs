using UnityEngine;
using Unity.Cinemachine;

namespace MMystery.Players
{
    [RequireComponent(typeof(Camera))]
    public class ThirdPersonCamera : MonoBehaviour
    {
        [SerializeField] private CinemachineCamera vcam;
        [SerializeField] private float mouseSensitivityX = 200f;
        [SerializeField] private float mouseSensitivityY = 120f;
        [SerializeField] private float minPitch = -20f;
        [SerializeField] private float maxPitch = 50f;

        private float _yaw = 0f;
        private float _pitch = 0f;
        private bool _isLocked = false;

        public float Yaw => _yaw;

        public void LockCursor(bool locked)
        {
            Cursor.lockState = locked ? CursorLockMode.Locked : CursorLockMode.None;
            Cursor.visible = !locked;
            _isLocked = locked;
        }

        private void Start()
        {
            // Lock cursor by default
            LockCursor(true);
        }

        private void Update()
        {
            if (!_isLocked) return;

            float mouseX = Input.GetAxis("Mouse X") * mouseSensitivityX * Time.deltaTime;
            float mouseY = Input.GetAxis("Mouse Y") * mouseSensitivityY * Time.deltaTime;

            _yaw += mouseX;
            _pitch = Mathf.Clamp(_pitch - mouseY, minPitch, maxPitch);

            transform.rotation = Quaternion.Euler(_pitch, _yaw, 0f);
        }
    }
}
