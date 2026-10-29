using UnityEngine;

// Baked data of one pedestrian body for CrowdSystem. Made by GTA > Build NPC Crowd (Editor/NpcPrefabs.cs), never by hand.
public class CrowdCharacter : ScriptableObject
{
    public Mesh mesh;                     // the body, vertex index in uv1.x (positions come from the VAT)
    public Material material;             // GTA/PS1Crowd with this body's VAT and outfit array
    public Material[] skins;              // PS1Lit outfits, same order as the array slices (used by the ragdolls)
    public int[] clipStart, clipFrames;   // VAT rows of each clip: 0 = idle, 1 = walk
    public AnimationClip[] clips;         // same clips, to pose the ragdoll on the frame the pedestrian was showing
    public float fps = 20;
    public bool eventOnly;                // protesters / riot police (gear baked in): never a walker
    public Vector3 lieHips, lieHead;      // root space, last frame of the fall clip (standing a ragdoll back up)
    public GameObject ragdoll;            // skinned model + Animator + physics bodies (kinematic until thrown)
}
