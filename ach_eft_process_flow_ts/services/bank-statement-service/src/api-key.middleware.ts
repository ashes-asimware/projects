import { Injectable, NestMiddleware } from '@nestjs/common';
import { Request, Response, NextFunction } from 'express';

@Injectable()
export class ApiKeyMiddleware implements NestMiddleware {
  use(req: Request, res: Response, next: NextFunction) {
    const expected = process.env.INTERNAL_API_KEY;
    const provided = (req.headers['x-api-key'] as string) || req.header('api-key');
    if (!expected) {
      res.status(401).json({ message: 'missing api key configuration' });
      return;
    }
    if (provided !== expected) {
      res.status(401).json({ message: 'unauthorized' });
      return;
    }
    next();
  }
}
