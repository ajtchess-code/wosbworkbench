# WoSB Workbench 4.12.4

- **Hit mesh in the 3D ship viewer**: tick "Hit mesh (where hits are drawn)" to see each ship's low-poly hitbox mesh (orange) inside the hull hitbox box (blue). From the client code: cannonballs are tested only against the box, which is the bounding box of this mesh; the mesh is used afterwards to place impact effects and fires on the hull.
- Hitbox data format v2 keeps the mesh. The next wiki build rebuilds the hitboxes once from the latest Full Recovery.
- Every hitbox the game uses, double-checked in code: hull box (balls, ship-to-ship collisions, mortar splash distance), mast boxes, sail boxes (up to three sails passed; furled sails use a smaller, lower test), and a bounding-sphere pre-check. Fire arrows and smoke skip masts and sails. The hit mesh never decides a hit; island meshes are only used against islands.
