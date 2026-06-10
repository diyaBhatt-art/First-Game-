using UnityEngine;

namespace MMystery.Players
{
    public static class CameraRelativeMovement
    {
        public static Vector3 GetCameraRelativeDirection(Vector2 input, float cameraYaw)
        {
            if (input.magnitude < 0.01f) return Vector3.zero;
            float yawRad = cameraYaw * Mathf.Deg2Rad;
            Vector3 forward = new Vector3(Mathf.Sin(yawRad), 0, Mathf.Cos(yawRad));
            Vector3 right = new Vector3(Mathf.Cos(yawRad), 0, -Mathf.Sin(yawRad));
            Vector3 dir = (forward * input.y + right * input.x).normalized;
            return dir;
        }
    }
}
