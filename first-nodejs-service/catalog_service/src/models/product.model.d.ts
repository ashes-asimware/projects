export class Product {
    readonly name: string;
    readonly description: string;
    readonly price: number;
    readonly stock: number;
    readonly id?: number | undefined;
    name: string;
    description: string;
    price: number;
    imageUrl: string;
    constructor(name: string, description: string, price: number, stock: number, id?: number | undefined);
}